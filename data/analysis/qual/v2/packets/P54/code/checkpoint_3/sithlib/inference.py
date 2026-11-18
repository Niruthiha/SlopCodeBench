"""Static inference.

Secret: how bindings and expressions are mapped to values (modules, classes,
functions, instances), how names are resolved through scopes, flow states,
star imports and builtins, how narrowing conditions restrict values, and how
the members of a value are enumerated.

Clients see these abstractions:
  * ``Project``  - opens the main file and returns a ``Location`` for a cursor.
  * ``Where``    - an evaluation point: a scope plus the flow state there.
  * ``Value``    - has ``kind``, ``type_name`` and ``members()``; evaluation
                   always yields a list of possible values (a union).
  * ``Entity``   - a named member/visible name with ``presentation()`` giving
                   ``(kind, type_name)`` and ``values()`` giving its values.
Name resolution yields *targets*: ``scopes.Binding`` objects for names bound
in source, or ``Entity`` objects for names provided at runtime.
"""

import ast
import builtins
import io
import os
import types

from . import flow, introspect, scopes, vocabulary
from .modules import (DIRECTORY, RUNTIME, SOURCE, ModuleLocator, directory_module_names,
                      runtime_submodule_names)

MODULE = "module"
CLASS = "class"
FUNCTION = "function"
INSTANCE = "instance"
PARAM = "param"
STATEMENT = "statement"
UNKNOWN = "unknown"

_LITERAL_TYPES = {
    ast.JoinedStr: str,
    ast.ListComp: list,
    ast.DictComp: dict,
    ast.SetComp: set,
    ast.GeneratorExp: types.GeneratorType,
    ast.Compare: bool,
}
_SEQUENCE_TYPES = {ast.List: list, ast.Tuple: tuple, ast.Set: set}
_ARITHMETIC_TYPES = (int, float, complex, str, bytes, list, tuple)
_PROPERTY_DECORATORS = ("property", "cached_property")
_SPECIAL_BUILTINS = ("type", "getattr", "enumerate", "zip", "sorted", "list", "reversed",
                     "iter", "set", "frozenset", "tuple", "next")

_FUNCTION_RETURNS = {
    "len": int, "repr": str, "ascii": str, "chr": str, "ord": int, "hash": int, "id": int,
    "input": str, "format": str, "bin": str, "oct": str, "hex": str, "isinstance": bool,
    "issubclass": bool, "callable": bool, "hasattr": bool, "all": bool, "any": bool,
    "sorted": list, "dir": list, "vars": dict, "globals": dict, "locals": dict,
    "round": int, "divmod": tuple, "open": io.TextIOWrapper,
}
_FUNCTION_RETURNS = {getattr(builtins, name): result
                     for name, result in _FUNCTION_RETURNS.items() if hasattr(builtins, name)}


def _method_table():
    table = {}

    def add(owner, result, names):
        for name in names.split():
            table[(owner, name)] = result

    add(str, str, "upper lower strip lstrip rstrip replace format join title capitalize "
                  "casefold center ljust rjust zfill swapcase expandtabs removeprefix "
                  "removesuffix translate format_map")
    add(str, list, "split rsplit splitlines")
    add(str, bool, "startswith endswith isalpha isdigit isalnum isspace islower isupper "
                   "istitle isdecimal isnumeric isidentifier isprintable isascii")
    add(str, int, "find rfind index rindex count")
    add(str, bytes, "encode")
    add(str, tuple, "partition rpartition")
    add(bytes, str, "decode hex")
    add(bytes, bytes, "upper lower strip lstrip rstrip replace join")
    add(bytes, list, "split rsplit splitlines")
    add(list, list, "copy")
    add(list, int, "index count")
    add(tuple, int, "index count")
    add(dict, dict, "copy")
    add(dict, type({}.keys()), "keys")
    add(dict, type({}.values()), "values")
    add(dict, type({}.items()), "items")
    add(set, set, "copy union intersection difference symmetric_difference")
    add(set, bool, "issubset issuperset isdisjoint")
    add(frozenset, frozenset, "copy union intersection difference symmetric_difference")
    add(int, int, "bit_length bit_count conjugate")
    add(int, bytes, "to_bytes")
    add(float, bool, "is_integer")
    add(float, str, "hex")
    return table


_METHOD_RETURNS = _method_table()


class _Slice:
    """Marker for a slice subscript."""


SLICE = _Slice()
UNKNOWN_INDEX = _Slice()


# ---------------------------------------------------------------------------
# Evaluation points

class Where:
    """A scope plus the flow state (None: the state at the end of the scope).

    ``frame`` optionally supplies argument values for the parameters of a
    function scope being called; ``local_values`` maps names bound inside an
    expression (comprehension variables) to their values.
    """

    def __init__(self, scope, state=None, frame=None, local_values=None):
        self.scope = scope
        self.state = state
        self.frame = frame
        self.local_values = local_values


class Arguments:
    """The argument expressions of one call, with where they are evaluated."""

    def __init__(self, node, where):
        self.positional = node.args
        self.keywords = node.keywords
        self.where = where


class Frame:
    """Parameter values for one call of a function scope."""

    def __init__(self, scope, bound=None, arguments=None):
        self.scope = scope
        self._mapping = {}
        params = sorted((e for e in scope.events if e.form == scopes.PARAM),
                        key=lambda e: e.details["index"])
        positional = [p for p in params
                      if not p.details["star"] and not p.details.get("keyword_only")]
        if bound is not None and positional:
            self._mapping[id(positional[0])] = list(bound)
            positional = positional[1:]
        if arguments is None:
            return
        for index, node in enumerate(arguments.positional):
            if isinstance(node, ast.Starred) or index >= len(positional):
                break
            self._mapping[id(positional[index])] = (node, arguments.where)
        for keyword in arguments.keywords:
            for param in params:
                if keyword.arg is not None and param.name == keyword.arg \
                        and not param.details["star"]:
                    self._mapping[id(param)] = (keyword.value, arguments.where)

    def param_values(self, binding):
        entry = self._mapping.get(id(binding))
        if entry is None:
            return None
        if isinstance(entry, list):
            return entry
        node, where = entry
        return where.scope.tree.analysis.evaluate(node, where)


def _unique(values):
    seen = set()
    result = []
    for value in values:
        key = value.key()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


# ---------------------------------------------------------------------------
# Values

class Value:
    kind = UNKNOWN
    type_name = None

    def key(self):
        return ("value", id(self))

    def members(self):
        return {}

    def attribute(self, name):
        entity = self.members().get(name)
        return entity.values() if entity is not None else []

    def attribute_targets(self, name):
        """Where attribute ``name`` is bound (Bindings or Entities)."""
        entity = self.members().get(name)
        return [entity] if entity is not None else []

    def call(self, arguments=None):
        return []

    def instantiate(self):
        return []

    def iterate(self):
        return []

    def subscript(self, index):
        return []

    def builtin_type(self):
        """For instances of builtin types, the type object; else None."""
        return None


class RuntimeValue(Value):
    """A live object obtained by importing a module."""

    def __init__(self, project, obj, owner=None):
        self.project = project
        self.obj = obj
        self._owner = owner
        self.kind = introspect.kind_of(obj)
        if self.kind == INSTANCE:
            self.type_name = introspect.type_name(obj)

    def key(self):
        return ("runtime", id(self.obj))

    def members(self):
        return {name: RuntimeEntity(self.project, name, self.obj)
                for name in introspect.attribute_names(self.obj)}

    def attribute(self, name):
        ok, value = introspect.get_attribute(self.obj, name)
        if ok:
            owner = self.obj if self.kind == CLASS else type(self.obj)
            return [RuntimeValue(self.project, value, owner)]
        if self.kind == MODULE:
            module_name = getattr(self.obj, "__name__", None)
            if module_name:
                found = self.project.module_value(module_name + "." + name)
                if found is not None:
                    return [found]
        return []

    def attribute_targets(self, name):
        ok, _ = introspect.get_attribute(self.obj, name)
        if ok:
            return [RuntimeEntity(self.project, name, self.obj)]
        return [ValueTarget(v) for v in self.attribute(name)]

    def call(self, arguments=None):
        if self.kind == CLASS:
            return self.instantiate()
        if self.kind == FUNCTION:
            try:
                result = _FUNCTION_RETURNS.get(self.obj)
            except TypeError:
                result = None
            if result is None and self._owner is not None:
                result = _method_return(self._owner, getattr(self.obj, "__name__", None))
            if result is not None:
                return [RuntimeInstance(self.project, result)]
        return []

    def instantiate(self):
        if self.kind == CLASS:
            return [RuntimeInstance(self.project, self.obj)]
        return []

    def iterate(self):
        if self.kind == INSTANCE:
            return RuntimeInstance(self.project, type(self.obj)).iterate()
        return []

    def subscript(self, index):
        if self.kind == CLASS:
            return [self]
        if self.kind == INSTANCE:
            return RuntimeInstance(self.project, type(self.obj)).subscript(index)
        return []

    def builtin_type(self):
        return type(self.obj) if self.kind == INSTANCE else None


def _method_return(owner, name):
    if not name or not isinstance(owner, type):
        return None
    for base in getattr(owner, "__mro__", (owner,)):
        result = _METHOD_RETURNS.get((base, name))
        if result is not None:
            return result
    return None


class RuntimeInstance(Value):
    """An instance of a runtime class, known only by its class."""

    kind = INSTANCE

    def __init__(self, project, cls):
        self.project = project
        self.cls = cls
        self._sample = introspect.sample_instance(cls)
        self.type_name = introspect.class_name(cls)

    def key(self):
        return ("instance", id(self.cls))

    def members(self):
        return {name: RuntimeEntity(self.project, name, self._sample, from_class=self.cls)
                for name in introspect.attribute_names(self.cls)}

    def attribute(self, name):
        return RuntimeEntity(self.project, name, self._sample, from_class=self.cls).values()

    def attribute_targets(self, name):
        if name in introspect.attribute_names(self.cls):
            return [RuntimeEntity(self.project, name, self._sample, from_class=self.cls)]
        return []

    def iterate(self):
        if issubclass(self.cls, str):
            return [RuntimeInstance(self.project, str)]
        if issubclass(self.cls, (bytes, bytearray, range)):
            return [RuntimeInstance(self.project, int)]
        return []

    def subscript(self, index):
        if index is SLICE and issubclass(self.cls, (str, bytes, list, tuple)):
            return [self]
        if issubclass(self.cls, str):
            return [RuntimeInstance(self.project, str)]
        if issubclass(self.cls, (bytes, bytearray)):
            return [RuntimeInstance(self.project, int)]
        return []

    def builtin_type(self):
        return self.cls


class SequenceInstance(RuntimeInstance):
    """A list/tuple/set display whose elements are known expressions."""

    def __init__(self, project, cls, node, where):
        RuntimeInstance.__init__(self, project, cls)
        self._node = node
        self._where = where

    def key(self):
        return ("display", id(self._node))

    def _analysis(self):
        return self._where.scope.tree.analysis

    def iterate(self):
        result = []
        for element in self._node.elts:
            if not isinstance(element, ast.Starred):
                result.extend(self._analysis().evaluate(element, self._where))
        return _unique(result)

    def subscript(self, index):
        if index is SLICE:
            return [self]
        elements = self._node.elts
        if isinstance(index, int) and not isinstance(index, bool) \
                and not any(isinstance(e, ast.Starred) for e in elements) \
                and -len(elements) <= index < len(elements) and self.cls is not set:
            return self._analysis().evaluate(elements[index], self._where)
        if self.cls is set:
            return []
        return self.iterate()


class ValueSequence(RuntimeInstance):
    """A container whose element values are known (one list per position).

    With ``positional`` the positions are fixed (a tuple); otherwise every
    element may be any of the listed values.
    """

    def __init__(self, project, cls, elements, positional=False):
        RuntimeInstance.__init__(self, project, cls)
        self._elements = elements
        self._positional = positional

    def key(self):
        return ("sequence", id(self))

    def iterate(self):
        return _unique([v for values in self._elements for v in values])

    def subscript(self, index):
        if index is SLICE:
            return [self]
        if self._positional and isinstance(index, int) and not isinstance(index, bool) \
                and -len(self._elements) <= index < len(self._elements):
            return self._elements[index]
        return self.iterate()


class DictInstance(RuntimeInstance):
    """A dict display whose keys and values are known expressions."""

    def __init__(self, project, node, where):
        RuntimeInstance.__init__(self, project, dict)
        self._node = node
        self._where = where

    def key(self):
        return ("display", id(self._node))

    def iterate(self):
        analysis = self._where.scope.tree.analysis
        result = []
        for key in self._node.keys:
            if key is not None:
                result.extend(analysis.evaluate(key, self._where))
        return _unique(result)

    def _values(self):
        analysis = self._where.scope.tree.analysis
        return _unique([v for k, value in zip(self._node.keys, self._node.values)
                        if k is not None for v in analysis.evaluate(value, self._where)])

    def attribute(self, name):
        if name in ("keys", "values", "items"):
            return [_DictView(self, name)]
        return RuntimeInstance.attribute(self, name)

    def subscript(self, index):
        analysis = self._where.scope.tree.analysis
        pairs = [(k, v) for k, v in zip(self._node.keys, self._node.values) if k is not None]
        if index is not UNKNOWN_INDEX and index is not SLICE:
            for key, value in pairs:
                if isinstance(key, ast.Constant) and type(key.value) is type(index) \
                        and key.value == index:
                    return analysis.evaluate(value, self._where)
        return _unique([v for _, value in pairs for v in analysis.evaluate(value, self._where)])


class _DictView(Value):
    """``keys``/``values``/``items`` of a dict display (a bound method)."""

    kind = FUNCTION

    def __init__(self, owner, which):
        self._owner = owner
        self.which = which

    def key(self):
        return ("dict-view", id(self._owner), self.which)

    def call(self, arguments=None):
        owner = self._owner
        project = owner.project
        keys, values = owner.iterate(), owner._values()
        if self.which == "keys":
            elements = [keys]
        elif self.which == "values":
            elements = [values]
        else:
            elements = [[ValueSequence(project, tuple, [keys, values], positional=True)]]
        return [ValueSequence(project, list, elements)]


class UnresolvedModule(Value):
    kind = MODULE


class DirectoryModule(Value):
    """A package directory without ``__init__.py``."""

    kind = MODULE

    def __init__(self, project, directory):
        self.project = project
        self.directory = directory

    def key(self):
        return ("directory", self.directory)

    def attribute(self, name):
        found = self.project.submodule_value(self.directory, name)
        return [found] if found is not None else []

    def attribute_targets(self, name):
        return [ValueTarget(v) for v in self.attribute(name)]


class StaticModule(Value):
    kind = MODULE

    def __init__(self, analysis):
        self.analysis = analysis

    def key(self):
        return ("module", self.analysis.path)

    def members(self):
        return self.analysis.module_members()

    def attribute_targets(self, name):
        analysis = self.analysis
        targets = [t for t, _ in analysis.resolve_local(name, Where(analysis.tree.module))]
        if targets:
            return targets
        package_dir = analysis.package_dir()
        if package_dir:
            found = analysis.project.submodule_value(package_dir, name)
            if found is not None:
                return [ValueTarget(found)]
        return []

    def attribute(self, name):
        result = []
        for target in self.attribute_targets(name):
            result.extend(self.analysis.target_values(target))
        return _unique(result)


class StaticFunction(Value):
    kind = FUNCTION

    def __init__(self, analysis, scope, bound=None):
        self.analysis = analysis
        self.scope = scope
        self.bound = bound  # values of the receiver for a bound method

    def key(self):
        return ("function", id(self.scope))

    def is_property(self):
        return any(name in _PROPERTY_DECORATORS for name in self.scope.decorator_names())

    def bind(self, receiver):
        """This function as a method looked up on ``receiver``."""
        decorators = self.scope.decorator_names()
        if "staticmethod" in decorators:
            return self
        if "classmethod" in decorators:
            if isinstance(receiver, StaticInstance):
                receiver = receiver.cls
            return StaticFunction(self.analysis, self.scope, [receiver])
        if receiver.kind == CLASS:
            return self
        return StaticFunction(self.analysis, self.scope, [receiver])

    def call(self, arguments=None):
        if self.scope.is_async():
            return []
        project = self.analysis.project
        key = ("call", id(self.scope))
        if not project.enter(key):
            return []
        try:
            frame = None
            if self.bound is not None or arguments is not None:
                frame = Frame(self.scope, self.bound, arguments)
            return self._returns(frame)
        finally:
            project.leave(key)

    def _returns(self, frame):
        analysis = self.analysis
        statements = self.scope.return_statements()
        if statements is None:
            return [RuntimeInstance(analysis.project, types.GeneratorType)]
        result = []
        for statement in statements:
            if statement.value is None:
                result.append(analysis.none_value())
            else:
                where = analysis.where_before(self.scope, statement)
                where.frame = frame
                result.extend(analysis.evaluate(statement.value, where))
        if not statements:
            result.append(analysis.none_value())
        result = _unique(result)
        if not result and self.scope.node.returns is not None:
            where = analysis.where_before(self.scope.parent, self.scope.node)
            result = analysis.annotation_values(self.scope.node.returns, where)
        return result


class StaticClass(Value):
    kind = CLASS

    def __init__(self, analysis, scope):
        self.analysis = analysis
        self.scope = scope
        self.name = scope.name

    def key(self):
        return ("class", id(self.scope))

    def bases(self):
        project = self.analysis.project
        key = ("bases", id(self.scope))
        if not project.enter(key):
            return []
        try:
            where = self.analysis.where_before(self.scope.parent, self.scope.node)
            result = []
            for expr in self.scope.base_expressions():
                for value in self.analysis.evaluate(expr, where):
                    if isinstance(value, StaticClass) and value.key() != self.key():
                        result.append(value)
            return _unique(result)
        finally:
            project.leave(key)

    def mro(self):
        return _linearize(self, set())

    def members(self):
        result = {}
        for cls in reversed(self.mro()):
            for event in cls.scope.all_events():
                if event.name and event.form != scopes.STAR:
                    result[event.name] = BindingEntity(cls.analysis, event)
        return result

    def instance_members(self):
        result = self.members()
        grouped = {}
        for cls in reversed(self.mro()):
            for event in cls.scope.instance_attribute_events():
                grouped.setdefault(event.name, []).append(event)
        for name, events in grouped.items():
            result[name] = AttributeEntity(self.analysis, events)
        return result

    def class_targets(self, name):
        for cls in self.mro():
            targets = [t for t, _ in cls.analysis.resolve_local(name, Where(cls.scope))]
            if targets:
                return targets
        return []

    def instance_targets(self, name):
        targets = []
        for cls in self.mro():
            targets.extend(e for e in cls.scope.instance_attribute_events() if e.name == name)
        return targets

    def attribute_targets(self, name):
        return self.class_targets(name)

    def attribute(self, name):
        result = []
        for target in self.class_targets(name):
            for value in self.analysis.target_values(target):
                result.append(value.bind(self) if isinstance(value, StaticFunction) else value)
        return _unique(result)

    def call(self, arguments=None):
        return [StaticInstance(self, arguments)]

    def instantiate(self):
        return [StaticInstance(self)]

    def subscript(self, index):
        return [self]

    def is_subclass_of(self, other):
        return any(cls.key() == other.key() for cls in self.mro())


class StaticInstance(Value):
    kind = INSTANCE

    def __init__(self, cls, arguments=None):
        self.cls = cls
        self.type_name = cls.name
        self.arguments = arguments  # constructor arguments, when known

    def key(self):
        return ("static-instance", self.cls.key())

    def members(self):
        return self.cls.instance_members()

    def attribute_targets(self, name):
        return self.cls.instance_targets(name) or self.cls.class_targets(name)

    def attribute(self, name):
        analysis = self.cls.analysis
        project = analysis.project
        key = ("attribute", self.cls.key(), name)
        if not project.enter(key):
            return []
        try:
            result = []
            for target in self.cls.instance_targets(name):
                method = target.home
                arguments = self.arguments if method.name == "__init__" else None
                frame = Frame(method, [self], arguments)
                result.extend(target.home.tree.analysis.binding_values(target, frame))
            if result or self.cls.instance_targets(name):
                return _unique(result)
            for target in self.cls.class_targets(name):
                for value in analysis.target_values(target):
                    if isinstance(value, StaticFunction):
                        value = value.bind(self)
                        if value.is_property():
                            result.extend(value.call())
                            continue
                    result.append(value)
            return _unique(result)
        finally:
            project.leave(key)

    def _dunder_call(self, name):
        result = []
        for value in self.attribute(name):
            result.extend(value.call())
        return _unique(result)

    def call(self, arguments=None):
        result = []
        for value in self.attribute("__call__"):
            result.extend(value.call(arguments))
        return _unique(result)

    def iterate(self):
        result = []
        for iterator in self._dunder_call("__iter__"):
            if isinstance(iterator, StaticInstance):
                result.extend(iterator._dunder_call("__next__"))
            else:
                result.extend(iterator.iterate())
        return _unique(result)

    def subscript(self, index):
        return self._dunder_call("__getitem__")


class ValueTarget:
    """A resolution target that is directly a value (e.g. a submodule)."""

    def __init__(self, value):
        self.value = value


def _linearize(cls, seen):
    """C3 linearization of statically known classes (DFS on conflict)."""
    if cls.key() in seen:
        return [cls]
    seen = seen | {cls.key()}
    bases = cls.bases()
    sequences = [_linearize(base, seen) for base in bases] + [list(bases)]
    result = [cls]
    sequences = [list(s) for s in sequences if s]
    while sequences:
        for sequence in sequences:
            head = sequence[0]
            if not any(head.key() in [c.key() for c in s[1:]] for s in sequences):
                break
        else:
            for sequence in sequences:
                for item in sequence:
                    if item.key() not in [c.key() for c in result]:
                        result.append(item)
            return result
        result.append(head)
        sequences = [[c for c in s if c.key() != head.key()] for s in sequences]
        sequences = [s for s in sequences if s]
    return result


# ---------------------------------------------------------------------------
# Entities

class Entity:
    name = None

    def presentation(self):
        return (STATEMENT, None)

    def values(self):
        return []


class RuntimeEntity(Entity):
    """An attribute of a live object, or of a class standing in for an instance."""

    def __init__(self, project, name, owner, from_class=None):
        self.project = project
        self.name = name
        self._owner = owner
        self._from_class = from_class

    def fetch(self):
        if self._owner is not None:
            return introspect.get_attribute(self._owner, self.name)
        ok, obj = introspect.get_attribute(self._from_class, self.name)
        if ok and introspect.is_data_descriptor(obj):
            return False, None
        return ok, obj

    def owner_name(self):
        """Qualified name of the object or class this is an attribute of."""
        owner = self._from_class if self._from_class is not None else self._owner
        if isinstance(owner, types.ModuleType):
            return owner.__name__
        if not isinstance(owner, type):
            owner = type(owner)
        return "%s.%s" % (owner.__module__, owner.__qualname__)

    def presentation(self):
        ok, obj = self.fetch()
        if not ok:
            return (STATEMENT, None)
        kind = introspect.kind_of(obj)
        if kind == INSTANCE:
            return (INSTANCE, introspect.type_name(obj))
        return (kind, None)

    def values(self):
        ok, obj = self.fetch()
        if not ok:
            return []
        owner = self._from_class
        if owner is None:
            owner = self._owner if isinstance(self._owner, type) else type(self._owner)
        return [RuntimeValue(self.project, obj, owner)]


class ValueEntity(Entity):
    """A name whose values are produced on demand (e.g. a submodule)."""

    def __init__(self, name, fetch, kind=None):
        self.name = name
        self._fetch = fetch
        self._kind = kind
        self._values = None

    def presentation(self):
        if self._kind is not None:
            return (self._kind, None)
        values = self.values()
        if not values:
            return (STATEMENT, None)
        if values[0].kind == INSTANCE:
            return (INSTANCE, values[0].type_name)
        if values[0].kind in (MODULE, CLASS, FUNCTION):
            return (values[0].kind, None)
        return (STATEMENT, None)

    def values(self):
        if self._values is None:
            found = self._fetch()
            self._values = [found] if isinstance(found, Value) else list(found or [])
        return list(self._values)


class BindingEntity(Entity):
    def __init__(self, analysis, binding):
        self._analysis = analysis
        self.binding = binding
        self.name = binding.name

    def presentation(self):
        form = self.binding.form
        if form == scopes.DEF:
            return (FUNCTION, None)
        if form == scopes.CLASS:
            return (CLASS, None)
        if form == scopes.PARAM:
            return (PARAM, None)
        if form == scopes.IMPORT:
            return (MODULE, None)
        if form in (scopes.IMPORT_FROM, scopes.ASSIGN, scopes.EXCEPT):
            values = self.values()
            value = values[0] if values else Value()
            if value.kind == INSTANCE:
                return (INSTANCE, value.type_name)
            if form == scopes.IMPORT_FROM and value.kind in (MODULE, CLASS, FUNCTION):
                return (value.kind, None)
        return (STATEMENT, None)

    def values(self):
        return self._analysis.binding_values(self.binding)


class AttributeEntity(Entity):
    """An instance attribute assigned (possibly several times) in methods."""

    def __init__(self, analysis, bindings):
        self._analysis = analysis
        self.bindings = bindings
        self.name = bindings[0].name

    def presentation(self):
        values = self.values()
        if values and values[0].kind == INSTANCE:
            return (INSTANCE, values[0].type_name)
        return (STATEMENT, None)

    def values(self):
        result = []
        for binding in self.bindings:
            result.extend(self._analysis.binding_values(binding))
        return _unique(result)


# ---------------------------------------------------------------------------
# Analysis of one file

class Analysis:
    """Inference over one source file."""

    def __init__(self, project, path, text):
        self.project = project
        self.path = path
        self.tree = scopes.ScopeTree(text, path)
        self.tree.analysis = self
        self._scope_by_node = {}
        self._index(self.tree.module)
        self._module_members = None
        self._flows = {}
        self._binding_cache = {}

    def _index(self, scope):
        for child in scope.children:
            self._scope_by_node[id(child.node)] = child
            self._index(child)

    def scope_of(self, node):
        return self._scope_by_node.get(id(node))

    def package_dir(self):
        if os.path.basename(self.path) == "__init__.py":
            return os.path.dirname(self.path)
        return None

    def location(self, line, col, indent):
        return Location(self, self.tree.scope_at(line, col), line, col, indent)

    def none_value(self):
        return RuntimeInstance(self.project, type(None))

    # -- flow ------------------------------------------------------------
    def flow(self, scope):
        analysis = scope.tree.analysis
        if analysis is not self:
            return analysis.flow(scope)
        found = self._flows.get(id(scope))
        if found is None:
            found = self._flows[id(scope)] = flow.Flow(scope)
        return found

    def where_before(self, scope, node):
        return Where(scope, self.flow(scope).state_before(node))

    # -- members ---------------------------------------------------------
    def module_members(self):
        if self._module_members is None:
            key = ("module", self.path)
            if not self.project.enter(key):
                return {}
            try:
                result = {}
                for event in self.tree.module.all_events():
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
        return self.project.exported_members(module)

    def dunder_all(self):
        """Names listed in this module's ``__all__``, or None without one."""
        key = ("__all__", self.path)
        if not self.project.enter(key):
            return None
        try:
            names = None
            for node in _module_level_nodes(self.tree.module.node.body):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets) \
                            and node.value is not None:
                        names = self._all_names(node.value) or []
                elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) \
                        and node.target.id == "__all__" and isinstance(node.op, ast.Add):
                    names = (names or []) + (self._all_names(node.value) or [])
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and isinstance(node.func.value, ast.Name) \
                        and node.func.value.id == "__all__" and names is not None \
                        and len(node.args) == 1:
                    method, arg = node.func.attr, node.args[0]
                    if method == "extend":
                        names = names + (self._all_names(arg) or [])
                    elif method == "append" and isinstance(arg, ast.Constant) \
                            and isinstance(arg.value, str):
                        names = names + [arg.value]
                    elif method == "remove" and isinstance(arg, ast.Constant):
                        names = [n for n in names if n != arg.value]
            return list(dict.fromkeys(names)) if names is not None else None
        finally:
            self.project.leave(key)

    def _all_names(self, node):
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return [e.value for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return (self._all_names(node.left) or []) + (self._all_names(node.right) or [])
        if isinstance(node, ast.Attribute) and node.attr == "__all__":
            names = []
            for value in self.evaluate(node.value, Where(self.tree.module)):
                found = self.project.dunder_all(value)
                if found:
                    names.extend(found)
            return names
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("list", "tuple") and len(node.args) == 1:
            return self._all_names(node.args[0])
        return None

    def visible(self, scope, line):
        result = {name: RuntimeEntity(self.project, name, vocabulary.builtin_namespace())
                  for name in vocabulary.builtin_names()}
        for level in reversed(scope.chain()):
            for event in level.events_until_line(line):
                self._apply(result, event)
        return result

    # -- name resolution -------------------------------------------------
    def resolve(self, name, where):
        """Targets ``name`` may refer to at ``where``: list of (target, constraints)."""
        scope = where.scope
        if scope.parent is not None and name in scope.globals_declared:
            module = scope
            while module.parent is not None:
                module = module.parent
            return self.resolve(name, Where(module))
        state = where.state if where.state is not None else self.flow(scope).end
        facts = state.facts(name)
        if facts:
            result = []
            for binding, constraints in sorted(facts, key=_fact_order):
                if binding is flow.OUTER:
                    for target, more in self._resolve_outer(name, scope):
                        result.append((target, more + constraints))
                else:
                    result.append((binding, constraints))
            return result
        for event in reversed(scope.events):
            if event.form == scopes.STAR:
                members = scope.tree.analysis.star_members(event)
                if name in members:
                    return [(members[name], ())]
        return self._resolve_outer(name, scope)

    def resolve_local(self, name, where):
        """Like ``resolve`` but without looking outside ``where.scope``."""
        state = where.state if where.state is not None else self.flow(where.scope).end
        facts = state.facts(name)
        if facts:
            return [(b, c) for b, c in sorted(facts, key=_fact_order) if b is not flow.OUTER]
        for event in reversed(where.scope.events):
            if event.form == scopes.STAR:
                members = where.scope.tree.analysis.star_members(event)
                if name in members:
                    return [(members[name], ())]
        return []

    def _resolve_outer(self, name, scope):
        parent = scope.parent
        while parent is not None and parent.kind == scopes.Scope.CLASS:
            parent = parent.parent
        if parent is None:
            if name in vocabulary.builtin_names():
                return [(RuntimeEntity(self.project, name, vocabulary.builtin_namespace()), ())]
            return []
        state = None
        if scope.kind == scopes.Scope.CLASS and scope.parent is parent:
            state = self.flow(parent).state_before(scope.node)
        return self.resolve(name, Where(parent, state))

    def target_values(self, target, frame=None):
        if isinstance(target, scopes.Binding):
            return target.home.tree.analysis.binding_values(target, frame)
        if isinstance(target, ValueTarget):
            return [target.value]
        return target.values()

    def name_values(self, name, where):
        if where.local_values and name in where.local_values:
            return where.local_values[name]
        result = []
        for target, constraints in self.resolve(name, where):
            values = self.target_values(target, where.frame)
            if constraints:
                values = self.narrow(values, constraints, where)
            result.extend(values)
        return _unique(result)

    def narrow(self, values, constraints, where):
        for constraint in constraints:
            if constraint.kind == flow.Constraint.NONE:
                if constraint.positive:
                    values = [self.none_value()]
                else:
                    values = [v for v in values if v.builtin_type() is not type(None)]
                continue
            classes = [c for c in self._class_values(constraint.expr, where)]
            if not classes:
                continue
            if constraint.positive:
                values = _unique([i for c in classes for i in c.instantiate()])
            else:
                values = [v for v in values if not any(_is_instance(v, c) for c in classes)]
        return values

    def _class_values(self, expr, where):
        if isinstance(expr, ast.Tuple):
            found = []
            for element in expr.elts:
                found.extend(self._class_values(element, where))
            return found
        return [v for v in self.evaluate(expr, where) if v.kind == CLASS]

    # -- bindings --------------------------------------------------------
    def binding_values(self, binding, frame=None):
        owner = binding.home.tree.analysis
        if owner is not self:
            return owner.binding_values(binding, frame)
        if frame is not None and binding.home is frame.scope:
            if binding.form == scopes.PARAM:
                found = frame.param_values(binding)
                if found:
                    return _unique(found)
            else:
                key = ("binding", id(binding), id(frame))
                if not self.project.enter(key):
                    return []
                try:
                    return _unique(self._binding_values(binding, frame))
                finally:
                    self.project.leave(key)
        cached = self._binding_cache.get(id(binding))
        if cached is not None:
            return cached
        key = ("binding", id(binding))
        if not self.project.enter(key):
            return []
        try:
            result = _unique(self._binding_values(binding))
        finally:
            self.project.leave(key)
        self._binding_cache[id(binding)] = result
        return result

    def _binding_values(self, binding, frame=None):
        form, details = binding.form, binding.details
        if form == scopes.DEF:
            return [StaticFunction(self, self.scope_of(binding.node))]
        if form == scopes.CLASS:
            return [StaticClass(self, self.scope_of(binding.node))]
        if form == scopes.PARAM:
            return self._param_values(binding)
        if form == scopes.IMPORT:
            found = self.project.module_value(details["module"], 0, self.path)
            return [found] if found is not None else []
        if form == scopes.IMPORT_FROM:
            return self._import_from_values(details)
        where = self.where_before(binding.home, binding.stmt) if binding.stmt is not None \
            else Where(binding.home)
        where.frame = frame
        if form == scopes.ASSIGN:
            if details.get("starred"):
                return [RuntimeInstance(self.project, list)]
            if details.get("annotation") is not None:
                annotated = self.annotation_values(details["annotation"], where)
                if annotated:
                    return annotated
            return self._unpacked(details.get("value"), details.get("path", ()), where)
        if form == scopes.OTHER and details.get("value") is not None:
            values = self.evaluate(details["value"], where)
            if details.get("source") == "for":
                values = [item for value in values for item in value.iterate()]
            elif details.get("source") == "with":
                values = [entered for value in values for entered in _entered(value)]
            return self.index_path(values, details.get("path", ()))
        if form == scopes.EXCEPT and details["type_expr"] is not None:
            return [i for c in self._class_values(details["type_expr"], where)
                    for i in c.instantiate()]
        return []

    def _unpacked(self, expr, path, where):
        if expr is None:
            return []
        direct = _unpack(expr, path)
        if direct is not None:
            return self.evaluate(direct, where)
        return self.index_path(self.evaluate(expr, where), path)

    @staticmethod
    def index_path(values, path):
        for index in path:
            values = _unique([item for value in values for item in value.subscript(index)])
        return values

    def _param_values(self, binding):
        details = binding.details
        function = details["function"]
        owner = function.class_scope()
        if details["index"] == 0 and owner is not None and not details["star"]:
            decorators = function.decorator_names()
            if "staticmethod" not in decorators:
                cls = StaticClass(self, owner)
                return [cls] if "classmethod" in decorators else cls.instantiate()
        if details["star"] == "*":
            return [RuntimeInstance(self.project, tuple)]
        if details["star"] == "**":
            return [RuntimeInstance(self.project, dict)]
        where = self.where_before(function.parent, function.node)
        if details["annotation"] is not None:
            annotated = self.annotation_values(details["annotation"], where)
            if annotated:
                return annotated
        if details.get("default") is not None:
            return self.evaluate(details["default"], where)
        return []

    def _import_from_values(self, details):
        module_name, level, attr = details["module"], details["level"], details["attr"]
        module = self.project.module_value(module_name, level, self.path)
        if module is not None:
            values = module.attribute(attr)
            if values:
                return values
        dotted = module_name + "." + attr if module_name else attr
        sub = self.project.module_value(dotted, level, self.path)
        return [sub] if sub is not None else []

    def import_from_targets(self, binding):
        """Where an imported name is bound in its own module."""
        details = binding.details
        module = self.project.module_value(details["module"], details["level"], self.path)
        if module is not None:
            targets = module.attribute_targets(details["attr"])
            if targets:
                return targets
        return []

    # -- annotations -----------------------------------------------------
    def annotation_values(self, node, where):
        if isinstance(node, ast.Constant):
            if node.value is None:
                return [self.none_value()]
            if isinstance(node.value, str):
                try:
                    parsed = ast.parse(node.value.strip(), mode="eval").body
                except (SyntaxError, ValueError, RecursionError, MemoryError):
                    return []
                return self.annotation_values(parsed, where)
            return []
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return _unique(self.annotation_values(node.left, where)
                           + self.annotation_values(node.right, where))
        if isinstance(node, ast.Subscript):
            head = _terminal_name(node.value)
            args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            if head == "Optional":
                return _unique(self.annotation_values(args[0], where) + [self.none_value()])
            if head == "Union":
                return _unique([v for a in args for v in self.annotation_values(a, where)])
            if head in ("Annotated", "ClassVar", "Final", "Required", "NotRequired",
                        "ReadOnly"):
                return self.annotation_values(args[0], where)
            if head in ("Type", "type"):
                return [v for v in self.evaluate(args[0], where) if v.kind == CLASS]
            return self._instances_of(self.evaluate(node.value, where))
        return self._instances_of(self.evaluate(node, where))

    def _instances_of(self, values):
        result = []
        for value in values:
            if value.kind == CLASS:
                result.extend(value.instantiate())
            elif isinstance(value, RuntimeValue):
                origin = getattr(value.obj, "__origin__", None)
                if isinstance(origin, type):
                    result.append(RuntimeInstance(self.project, origin))
        return _unique(result)

    # -- expressions -----------------------------------------------------
    def evaluate(self, node, where):
        project = self.project
        if isinstance(node, ast.Constant):
            return [RuntimeInstance(project, type(node.value))]
        sequence = _SEQUENCE_TYPES.get(type(node))
        if sequence is not None:
            return [SequenceInstance(project, sequence, node, where)]
        if isinstance(node, ast.Dict):
            return [DictInstance(project, node, where)]
        literal = _LITERAL_TYPES.get(type(node))
        if literal is not None:
            return [RuntimeInstance(project, literal)]
        if isinstance(node, ast.Name):
            return self.name_values(node.id, where)
        if isinstance(node, ast.Attribute):
            result = []
            for value in self.evaluate(node.value, where):
                result.extend(value.attribute(node.attr))
            return _unique(result)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "super":
                found = self._super_values(where)
                if found is not None:
                    return found
            if isinstance(node.func, ast.Name) and node.func.id in _SPECIAL_BUILTINS:
                found = self._builtin_call(node, where)
                if found is not None:
                    return found
            arguments = Arguments(node, where)
            result = []
            for value in self.evaluate(node.func, where):
                result.extend(value.call(arguments))
            return _unique(result)
        if isinstance(node, ast.Subscript):
            index = _index_of(node.slice)
            result = []
            for value in self.evaluate(node.value, where):
                result.extend(value.subscript(index))
            return _unique(result)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return [RuntimeInstance(project, bool)]
            return self.evaluate(node.operand, where)
        if isinstance(node, ast.BinOp):
            return self._binary(node, where)
        if isinstance(node, ast.BoolOp):
            return _unique([v for operand in node.values for v in self.evaluate(operand, where)])
        if isinstance(node, ast.IfExp):
            return _unique(self.evaluate(node.body, where) + self.evaluate(node.orelse, where))
        if isinstance(node, ast.NamedExpr):
            return self.evaluate(node.value, where)
        return []

    def _binary(self, node, where):
        result = []
        lefts = self.evaluate(node.left, where)
        rights = None
        for left in lefts:
            left_type = left.builtin_type()
            if left_type is str and isinstance(node.op, ast.Mod):
                result.append(left)
                continue
            if rights is None:
                rights = self.evaluate(node.right, where)
            for right in rights:
                if left_type is not None and left_type is right.builtin_type() \
                        and left_type in _ARITHMETIC_TYPES:
                    result.append(RuntimeInstance(self.project, left_type))
        return _unique(result)

    def _builtin_call(self, node, where):
        """Calls of builtins whose result depends on their arguments."""
        name = node.func.id
        functions = self.evaluate(node.func, where)
        if len(functions) != 1 or not isinstance(functions[0], RuntimeValue) \
                or functions[0].obj is not getattr(builtins, name, None) \
                or any(isinstance(a, ast.Starred) for a in node.args):
            return None
        args = node.args
        project = self.project
        if name == "type" and len(args) == 1:
            result = []
            for value in self.evaluate(args[0], where):
                if isinstance(value, StaticInstance):
                    result.append(value.cls)
                elif isinstance(value, RuntimeInstance):
                    result.append(RuntimeValue(project, value.cls))
            return _unique(result)
        if name == "getattr" and len(args) >= 2 and isinstance(args[1], ast.Constant) \
                and isinstance(args[1].value, str):
            result = []
            for value in self.evaluate(args[0], where):
                result.extend(value.attribute(args[1].value))
            if len(args) > 2:
                result.extend(self.evaluate(args[2], where))
            return _unique(result)
        if not args:
            return None
        items = [[v for value in self.evaluate(a, where) for v in value.iterate()]
                 for a in args]
        if name == "enumerate":
            pair = ValueSequence(project, tuple, [[RuntimeInstance(project, int)], items[0]],
                                 positional=True)
            return [ValueSequence(project, enumerate, [[pair]])]
        if name == "zip":
            group = ValueSequence(project, tuple, items, positional=True)
            return [ValueSequence(project, zip, [[group]])]
        if name in ("sorted", "list", "reversed", "iter"):
            cls = {"sorted": list, "list": list, "reversed": reversed, "iter": type(iter([]))}
            return [ValueSequence(project, cls[name], [items[0]])]
        if name in ("set", "frozenset", "tuple"):
            return [ValueSequence(project, getattr(builtins, name), [items[0]])]
        if name == "next":
            return items[0]
        return None

    def _super_values(self, where):
        scope = where.scope
        owner = scope.class_scope() if scope.kind == scopes.Scope.FUNCTION else None
        if owner is None:
            return None
        cls = StaticClass(owner.tree.analysis, owner)
        params = sorted((e for e in scope.events if e.form == scopes.PARAM),
                        key=lambda e: e.details["index"])
        receivers = self.name_values(params[0].name, where) if params else []
        arguments = [r.arguments for r in receivers if isinstance(r, StaticInstance)] or [None]
        return _unique([StaticInstance(base, arguments[0]) for base in cls.bases()])


def _module_level_nodes(statements):
    """Nodes executed at module level (nested scopes are not entered)."""
    stack = list(reversed(statements))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _fact_order(fact):
    binding = fact[0]
    return getattr(binding, "order", 0)


def _is_instance(value, cls):
    if isinstance(value, StaticInstance) and isinstance(cls, StaticClass):
        return value.cls.is_subclass_of(cls)
    if isinstance(cls, RuntimeValue) and value.builtin_type() is not None:
        try:
            return issubclass(value.builtin_type(), cls.obj)
        except TypeError:
            return False
    return False


def _entered(value):
    if isinstance(value, StaticInstance):
        entered = value._dunder_call("__enter__")
        if entered:
            return entered
    return [value]


def _terminal_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _index_of(node):
    if isinstance(node, ast.Slice):
        return SLICE
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) \
            and isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, int):
        return -node.operand.value
    return UNKNOWN_INDEX


def _unpack(expr, path):
    for index in path:
        if not isinstance(expr, (ast.Tuple, ast.List)):
            return None
        if any(isinstance(e, ast.Starred) for e in expr.elts) or index >= len(expr.elts):
            return None
        expr = expr.elts[index]
    return expr


class Location:
    """A cursor position inside the main file (for completion)."""

    def __init__(self, analysis, scope, line, col, indent):
        self._analysis = analysis
        self._scope = scope
        self._line = line
        self._where = Where(scope, analysis.flow(scope).state_at(line, col, indent))

    def visible_entities(self):
        return self._analysis.visible(self._scope, self._line)

    def evaluate(self, expression_text):
        """Possible values of an expression written at the cursor."""
        try:
            node = ast.parse(expression_text.strip(), mode="eval").body
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return []
        return self._analysis.evaluate(node, self._where)


# ---------------------------------------------------------------------------
# Project

class Project:
    def __init__(self, main_path, main_text, root=None):
        self._main_path = os.path.abspath(main_path)
        self.root = os.path.abspath(root) if root else os.path.dirname(self._main_path)
        self._locator = ModuleLocator(self.root)
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

    def location(self, line, col, indent=0):
        return self.main.location(line, col, indent)

    def module_value(self, dotted, level=0, importer_path=None):
        located = self._locator.locate(dotted, level, importer_path or self._main_path)
        return self._wrap(located)

    def submodule_value(self, directory, name):
        return self._wrap(self._locator.locate_in_directory(directory, name))

    # -- module contents -------------------------------------------------
    def dunder_all(self, module):
        """The ``__all__`` names of a module value, or None."""
        if isinstance(module, StaticModule):
            return module.analysis.dunder_all()
        if isinstance(module, RuntimeValue) and module.kind == MODULE:
            ok, names = introspect.get_attribute(module.obj, "__all__")
            if ok and isinstance(names, (list, tuple)):
                return [n for n in names if isinstance(n, str)]
        return None

    def exported_members(self, module):
        """Names ``from <module> import *`` binds: dict of name -> Entity."""
        if module.kind != MODULE:
            return {}
        members = module.members()
        names = self.dunder_all(module)
        if names is None:
            return {name: entity for name, entity in members.items()
                    if not name.startswith("_")}
        result = {}
        for name in names:
            if name in members:
                result[name] = members[name]
            else:
                result[name] = ValueEntity(name, lambda n=name: module.attribute(n))
        return result

    def importable_members(self, module):
        """Names offered after ``from <module> import``: dict of name -> Entity."""
        result = self.exported_members(module)
        if self.dunder_all(module) is not None:
            return result
        for name, entity in self.submodule_entities(module).items():
            if not name.startswith("_"):
                result.setdefault(name, entity)
        return result

    def submodule_entities(self, module):
        """Submodules of a package value: dict of name -> Entity."""
        names = set()
        directory = None
        if isinstance(module, StaticModule):
            directory = module.analysis.package_dir()
        elif isinstance(module, DirectoryModule):
            directory = module.directory
        elif isinstance(module, RuntimeValue) and module.kind == MODULE:
            names = runtime_submodule_names(module.obj)
            prefix = module.obj.__name__
            return {name: ValueEntity(name, lambda n=name: self.module_value(prefix + "." + n),
                                      MODULE) for name in names}
        if directory is None:
            return {}
        names = directory_module_names(directory)
        return {name: ValueEntity(name, lambda n=name: self.submodule_value(directory, n),
                                  MODULE) for name in names}

    def module_names(self, dotted="", level=0):
        """Modules importable as ``[.*]<dotted>.<name>``: dict of name -> Entity."""
        if not dotted and level == 0:
            return {name: ValueEntity(name, lambda n=name: self.module_value(n), MODULE)
                    for name in self._locator.top_level_names(self._main_path)}
        if not dotted:
            base = self._locator.relative_base(level, self._main_path)
            if base is None:
                return {}
            return self.submodule_entities(DirectoryModule(self, base))
        module = self.module_value(dotted, level)
        return self.submodule_entities(module) if module is not None else {}

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
