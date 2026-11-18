"""Static inference.

Secret: how bindings and expressions are mapped to values (modules, classes,
functions, instances), how names are resolved through scopes, star imports
and builtins, and how the members of a value are enumerated.

Clients see three abstractions:
  * ``Project``  - opens the main file and returns a ``Location`` for a cursor.
  * ``Value``    - has ``kind``, ``type_name`` and ``members()``.
  * ``Entity``   - a named member/visible name with ``presentation()`` giving
                   ``(kind, type_name)`` and ``value()`` giving a ``Value``.
"""

import ast
import os
import types

from . import introspect, scopes, vocabulary
from .modules import DIRECTORY, RUNTIME, SOURCE, ModuleLocator

MODULE = "module"
CLASS = "class"
FUNCTION = "function"
INSTANCE = "instance"
PARAM = "param"
STATEMENT = "statement"
UNKNOWN = "unknown"

_LITERAL_TYPES = {
    ast.JoinedStr: str,
    ast.List: list, ast.ListComp: list,
    ast.Tuple: tuple,
    ast.Dict: dict, ast.DictComp: dict,
    ast.Set: set, ast.SetComp: set,
    ast.GeneratorExp: types.GeneratorType,
    ast.Compare: bool,
}
_ARITHMETIC_TYPES = (int, float, complex, str, bytes, list, tuple)


# ---------------------------------------------------------------------------
# Values

class Value:
    kind = UNKNOWN
    type_name = None

    def members(self):
        return {}

    def attribute(self, name):
        entity = self.members().get(name)
        return entity.value() if entity is not None else UNKNOWN_VALUE

    def call(self):
        return UNKNOWN_VALUE

    def instantiate(self):
        return UNKNOWN_VALUE

    def builtin_type(self):
        """For instances of builtin types, the type object; else None."""
        return None


UNKNOWN_VALUE = Value()


class RuntimeValue(Value):
    """A live object obtained by importing a module."""

    def __init__(self, project, obj):
        self._project = project
        self._obj = obj
        self.kind = introspect.kind_of(obj)
        if self.kind == INSTANCE:
            self.type_name = introspect.type_name(obj)

    def members(self):
        return {name: RuntimeEntity(self._project, name, self._obj)
                for name in introspect.attribute_names(self._obj)}

    def attribute(self, name):
        ok, value = introspect.get_attribute(self._obj, name)
        if ok:
            return RuntimeValue(self._project, value)
        if self.kind == MODULE:
            module_name = getattr(self._obj, "__name__", None)
            if module_name:
                found = self._project.module_value(module_name + "." + name)
                if found is not None:
                    return found
        return UNKNOWN_VALUE

    def call(self):
        return self.instantiate()

    def instantiate(self):
        if self.kind == CLASS:
            return RuntimeInstance(self._project, self._obj)
        return UNKNOWN_VALUE

    def builtin_type(self):
        return type(self._obj) if self.kind == INSTANCE else None


class RuntimeInstance(Value):
    """An instance of a runtime class, known only by its class."""

    kind = INSTANCE

    def __init__(self, project, cls):
        self._project = project
        self._cls = cls
        self._sample = introspect.sample_instance(cls)
        self.type_name = introspect.class_name(cls)

    def members(self):
        return {name: RuntimeEntity(self._project, name, self._sample, from_class=self._cls)
                for name in introspect.attribute_names(self._cls)}

    def attribute(self, name):
        return RuntimeEntity(self._project, name, self._sample, from_class=self._cls).value()

    def builtin_type(self):
        return self._cls


class UnresolvedModule(Value):
    kind = MODULE


class DirectoryModule(Value):
    """A package directory without ``__init__.py``."""

    kind = MODULE

    def __init__(self, project, directory):
        self._project = project
        self._directory = directory

    def attribute(self, name):
        found = self._project.submodule_value(self._directory, name)
        return found if found is not None else UNKNOWN_VALUE


class StaticModule(Value):
    kind = MODULE

    def __init__(self, analysis):
        self._analysis = analysis

    def members(self):
        return self._analysis.module_members()

    def attribute(self, name):
        entity = self.members().get(name)
        if entity is not None:
            return entity.value()
        package_dir = self._analysis.package_dir()
        if package_dir:
            found = self._analysis.project.submodule_value(package_dir, name)
            if found is not None:
                return found
        return UNKNOWN_VALUE


class StaticFunction(Value):
    kind = FUNCTION

    def __init__(self, analysis, scope):
        self._analysis = analysis
        self._scope = scope

    def call(self):
        if self._scope.is_async():
            return UNKNOWN_VALUE
        project = self._analysis.project
        key = ("call", id(self._scope))
        if not project.enter(key):
            return UNKNOWN_VALUE
        try:
            view = _View(scope=self._scope, order=float("inf"))
            for expr in self._scope.returned_expressions():
                value = self._analysis.evaluate(expr, self._scope, view)
                if value.kind != UNKNOWN:
                    return value
            return UNKNOWN_VALUE
        finally:
            project.leave(key)


class StaticClass(Value):
    kind = CLASS

    def __init__(self, analysis, scope):
        self._analysis = analysis
        self._scope = scope
        self.name = scope.name

    def identity(self):
        return id(self._scope)

    def bases(self):
        project = self._analysis.project
        key = ("bases", id(self._scope))
        if not project.enter(key):
            return []
        try:
            parent = self._scope.parent
            view = _View()
            result = []
            for expr in self._scope.base_expressions():
                value = self._analysis.evaluate(expr, parent, view)
                if isinstance(value, StaticClass) and value.identity() != self.identity():
                    result.append(value)
            return result
        finally:
            project.leave(key)

    def mro(self):
        return _linearize(self, set())

    def members(self):
        result = {}
        for cls in reversed(self.mro()):
            for event in cls._scope.all_events():
                if event.name and event.form != scopes.STAR:
                    result[event.name] = BindingEntity(cls._analysis, event)
        return result

    def instance_members(self):
        result = self.members()
        for cls in reversed(self.mro()):
            for event in cls._scope.instance_attribute_events():
                result[event.name] = BindingEntity(cls._analysis, event)
        return result

    def call(self):
        return self.instantiate()

    def instantiate(self):
        return StaticInstance(self)


class StaticInstance(Value):
    kind = INSTANCE

    def __init__(self, cls):
        self._cls = cls
        self.type_name = cls.name

    def members(self):
        return self._cls.instance_members()


def _linearize(cls, seen):
    """C3 linearization of statically known classes (DFS on conflict)."""
    if cls.identity() in seen:
        return [cls]
    seen = seen | {cls.identity()}
    bases = cls.bases()
    sequences = [_linearize(base, seen) for base in bases] + [list(bases)]
    result = [cls]
    sequences = [list(s) for s in sequences if s]
    while sequences:
        for sequence in sequences:
            head = sequence[0]
            if not any(head.identity() in [c.identity() for c in s[1:]] for s in sequences):
                break
        else:
            for sequence in sequences:
                for item in sequence:
                    if item.identity() not in [c.identity() for c in result]:
                        result.append(item)
            return result
        result.append(head)
        sequences = [[c for c in s if c.identity() != head.identity()] for s in sequences]
        sequences = [s for s in sequences if s]
    return result


# ---------------------------------------------------------------------------
# Entities

class Entity:
    name = None

    def presentation(self):
        return (STATEMENT, None)

    def value(self):
        return UNKNOWN_VALUE


class RuntimeEntity(Entity):
    """An attribute of a live object, or of a class standing in for an instance."""

    def __init__(self, project, name, owner, from_class=None):
        self._project = project
        self.name = name
        self._owner = owner
        self._from_class = from_class

    def _fetch(self):
        if self._owner is not None:
            return introspect.get_attribute(self._owner, self.name)
        ok, obj = introspect.get_attribute(self._from_class, self.name)
        if ok and introspect.is_data_descriptor(obj):
            return False, None
        return ok, obj

    def presentation(self):
        ok, obj = self._fetch()
        if not ok:
            return (STATEMENT, None)
        kind = introspect.kind_of(obj)
        if kind == INSTANCE:
            return (INSTANCE, introspect.type_name(obj))
        return (kind, None)

    def value(self):
        ok, obj = self._fetch()
        return RuntimeValue(self._project, obj) if ok else UNKNOWN_VALUE


class BindingEntity(Entity):
    def __init__(self, analysis, binding):
        self._analysis = analysis
        self._binding = binding
        self.name = binding.name
        self._value = None

    def presentation(self):
        form = self._binding.form
        if form == scopes.DEF:
            return (FUNCTION, None)
        if form == scopes.CLASS:
            return (CLASS, None)
        if form == scopes.PARAM:
            return (PARAM, None)
        if form == scopes.IMPORT:
            return (MODULE, None)
        if form in (scopes.IMPORT_FROM, scopes.ASSIGN, scopes.EXCEPT):
            value = self.value()
            if value.kind == INSTANCE:
                return (INSTANCE, value.type_name)
            if form == scopes.IMPORT_FROM and value.kind in (MODULE, CLASS, FUNCTION):
                return (value.kind, None)
        return (STATEMENT, None)

    def value(self):
        if self._value is None:
            project = self._analysis.project
            key = ("binding", id(self._binding))
            if not project.enter(key):
                return UNKNOWN_VALUE
            try:
                self._value = self._analysis.binding_value(self._binding)
            finally:
                project.leave(key)
        return self._value


# ---------------------------------------------------------------------------
# Name resolution

class _View:
    """Which events of each scope are visible for a lookup."""

    def __init__(self, line=None, scope=None, order=None):
        self._line = line
        self._scope = scope
        self._order = order

    def events(self, scope):
        if self._line is not None:
            return scope.events_until_line(self._line)
        if scope is self._scope and self._order is not None:
            return scope.events_before(self._order)
        return scope.all_events()


class Analysis:
    """Inference over one source file."""

    def __init__(self, project, path, text):
        self.project = project
        self.path = path
        self._tree = scopes.ScopeTree(text)
        self._scope_by_node = {}
        self._index(self._tree.module)
        self._module_members = None

    def _index(self, scope):
        for child in scope.children:
            self._scope_by_node[id(child.node)] = child
            self._index(child)

    def package_dir(self):
        if os.path.basename(self.path) == "__init__.py":
            return os.path.dirname(self.path)
        return None

    def location(self, line, col):
        return Location(self, self._tree.scope_at(line, col), line)

    # -- members ---------------------------------------------------------
    def module_members(self):
        if self._module_members is None:
            key = ("module", self.path)
            if not self.project.enter(key):
                return {}
            try:
                result = {}
                for event in self._tree.module.all_events():
                    self._apply(result, event)
                self._module_members = result
            finally:
                self.project.leave(key)
        return self._module_members

    def _apply(self, result, event):
        if event.form == scopes.STAR:
            result.update(self.star_members(event))
        elif event.name:
            result[event.name] = BindingEntity(self, event)

    def star_members(self, event):
        module = self.project.module_value(event.details["module"], event.details["level"],
                                           self.path)
        if module is None:
            return {}
        return {name: entity for name, entity in module.members().items()
                if not name.startswith("_")}

    def visible(self, scope, view):
        result = {name: RuntimeEntity(self.project, name, vocabulary.builtin_namespace())
                  for name in vocabulary.builtin_names()}
        for level in reversed(scope.chain()):
            for event in view.events(level):
                self._apply(result, event)
        return result

    def lookup(self, name, scope, view):
        for level in scope.chain():
            for event in reversed(view.events(level)):
                if event.form == scopes.STAR:
                    members = self.star_members(event)
                    if name in members:
                        return members[name]
                elif event.name == name:
                    return BindingEntity(self, event)
        if name in vocabulary.builtin_names():
            return RuntimeEntity(self.project, name, vocabulary.builtin_namespace())
        return None

    # -- bindings --------------------------------------------------------
    def binding_value(self, binding):
        form, details = binding.form, binding.details
        view = _View(scope=binding.scope, order=binding.order)
        if form == scopes.DEF:
            return StaticFunction(self, self._scope_by_node[id(details["node"])])
        if form == scopes.CLASS:
            return StaticClass(self, self._scope_by_node[id(details["node"])])
        if form == scopes.PARAM:
            return self._param_value(binding, view)
        if form == scopes.IMPORT:
            found = self.project.module_value(details["module"], 0, self.path)
            return found if found is not None else UnresolvedModule()
        if form == scopes.IMPORT_FROM:
            return self._import_from_value(details)
        if form == scopes.ASSIGN:
            value = UNKNOWN_VALUE
            expr = _unpack(details["value"], details["path"])
            if expr is not None:
                value = self.evaluate(expr, binding.scope, view)
            if value.kind != INSTANCE and details.get("annotation") is not None:
                annotated = self.evaluate(details["annotation"], binding.scope, view)
                if annotated.kind == CLASS:
                    value = annotated.instantiate()
            return value
        if form == scopes.EXCEPT and details["type_expr"] is not None:
            exc_type = self.evaluate(details["type_expr"], binding.scope, view)
            if exc_type.kind == CLASS:
                return exc_type.instantiate()
        return UNKNOWN_VALUE

    def _param_value(self, binding, view):
        details = binding.details
        function = details["function"]
        owner = function.class_scope()
        if details["index"] == 0 and owner is not None and not details["star"]:
            decorators = function.decorator_names()
            if "staticmethod" not in decorators:
                cls = StaticClass(self, owner)
                return cls if "classmethod" in decorators else cls.instantiate()
        if details["star"] == "*":
            return RuntimeInstance(self.project, tuple)
        if details["star"] == "**":
            return RuntimeInstance(self.project, dict)
        if details["annotation"] is not None:
            annotated = self.evaluate(details["annotation"], function.parent, _View())
            if annotated.kind == CLASS:
                return annotated.instantiate()
        return UNKNOWN_VALUE

    def _import_from_value(self, details):
        module_name, level, attr = details["module"], details["level"], details["attr"]
        module = self.project.module_value(module_name, level, self.path)
        if module is not None:
            value = module.attribute(attr)
            if value.kind != UNKNOWN:
                return value
        dotted = module_name + "." + attr if module_name else attr
        sub = self.project.module_value(dotted, level, self.path)
        return sub if sub is not None else UNKNOWN_VALUE

    # -- expressions -----------------------------------------------------
    def evaluate(self, node, scope, view):
        project = self.project
        if isinstance(node, ast.Constant):
            return RuntimeInstance(project, type(node.value))
        literal = _LITERAL_TYPES.get(type(node))
        if literal is not None:
            return RuntimeInstance(project, literal)
        if isinstance(node, ast.Name):
            entity = self.lookup(node.id, scope, view)
            return entity.value() if entity is not None else UNKNOWN_VALUE
        if isinstance(node, ast.Attribute):
            return self.evaluate(node.value, scope, view).attribute(node.attr)
        if isinstance(node, ast.Call):
            return self.evaluate(node.func, scope, view).call()
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return RuntimeInstance(project, bool)
            return self.evaluate(node.operand, scope, view)
        if isinstance(node, ast.BinOp):
            left = self.evaluate(node.left, scope, view)
            left_type = left.builtin_type()
            if left_type is str and isinstance(node.op, ast.Mod):
                return left
            right_type = self.evaluate(node.right, scope, view).builtin_type()
            if left_type is not None and left_type is right_type \
                    and left_type in _ARITHMETIC_TYPES:
                return left
        return UNKNOWN_VALUE


def _unpack(expr, path):
    for index in path:
        if not isinstance(expr, (ast.Tuple, ast.List)):
            return None
        if any(isinstance(e, ast.Starred) for e in expr.elts) or index >= len(expr.elts):
            return None
        expr = expr.elts[index]
    return expr


class Location:
    """A cursor position inside the main file."""

    def __init__(self, analysis, scope, line):
        self._analysis = analysis
        self._scope = scope
        self._view = _View(line=line)

    def visible_entities(self):
        return self._analysis.visible(self._scope, self._view)

    def evaluate(self, expression_text):
        try:
            node = ast.parse(expression_text.strip(), mode="eval").body
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return UNKNOWN_VALUE
        return self._analysis.evaluate(node, self._scope, self._view)


# ---------------------------------------------------------------------------
# Project

class Project:
    def __init__(self, main_path, main_text):
        self._main_path = os.path.abspath(main_path)
        self._locator = ModuleLocator(os.path.dirname(self._main_path))
        self._analyses = {}
        self._active = set()
        self.main = Analysis(self, self._main_path, main_text)
        self._analyses[self._main_path] = self.main

    def enter(self, key):
        if key in self._active:
            return False
        self._active.add(key)
        return True

    def leave(self, key):
        self._active.discard(key)

    def location(self, line, col):
        return self.main.location(line, col)

    def module_value(self, dotted, level=0, importer_path=None):
        located = self._locator.locate(dotted, level, importer_path or self._main_path)
        return self._wrap(located)

    def submodule_value(self, directory, name):
        return self._wrap(self._locator.locate_in_directory(directory, name))

    def _wrap(self, located):
        if located is None:
            return None
        if located.how == RUNTIME:
            return RuntimeValue(self, located.module)
        if located.how == DIRECTORY:
            return DirectoryModule(self, located.path)
        if located.how == SOURCE:
            return StaticModule(self._analysis_for(located.path))
        return None

    def _analysis_for(self, path):
        path = os.path.abspath(path)
        if path not in self._analyses:
            try:
                with open(path, "rb") as handle:
                    text = handle.read().decode("utf-8", errors="replace")
            except OSError:
                text = ""
            self._analyses[path] = Analysis(self, path, text)
        return self._analyses[path]
