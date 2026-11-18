"""Definition navigation (``goto`` and ``infer``).

Secret: how the identifier under the cursor (or every identifier spelled
some way) is found and classified (plain name, attribute, definition header,
parameter, import part, keyword argument, comprehension variable), what each
command answers for it, what identifies the symbol it denotes, and how
bindings and values are described as definition records (names, qualified
names, positions, descriptions, docstrings).
"""

import ast
import inspect
import os
import re
import types

from . import flow, inference, introspect, scopes
from .inference import (DictInstance, DirectoryModule, RuntimeEntity, RuntimeInstance,
                        RuntimeValue, StaticClass, StaticFunction, StaticInstance,
                        StaticModule, Where)
from .source import SourceFile

GOTO = "goto"
INFER = "infer"


class NotOnName(Exception):
    """The cursor does not touch an identifier."""


def run(command, path, line, col, root=None, follow_imports=False):
    """Definitions (as dicts) answering ``command`` at the cursor.

    With ``follow_imports``, ``goto`` continues through import statements to
    the definitions they finally name.
    """
    source = SourceFile(path)
    source.check_position(line, col)
    project = inference.Project(source.path, source.text(), root)
    analysis = project.main
    occurrence = _Finder(analysis, line, col).find()
    if occurrence is None:
        raise NotOnName("no name at %d:%d" % (line, col))
    describer = _Describer(project)
    if command == GOTO:
        targets = occurrence.goto()
        if follow_imports:
            targets = _Follower(project).follow(targets)
        records = describer.targets(targets)
    else:
        records = describer.values(occurrence.infer())
    unique = {}
    for record in records:
        if record is not None:
            unique.setdefault(tuple(sorted(record.items())), record)
    return sorted(unique.values(),
                  key=lambda r: (r["module_path"], r["line"], r["column"], r["name"]))


def find(analysis, line, col):
    """``(name, line, column, occurrence)`` for the identifier at the cursor, or None."""
    return _Finder(analysis, line, col, named=True).find()


def occurrences(analysis, name):
    """Every identifier spelled ``name`` in ``analysis``'s file:
    list of ``(line, column, occurrence)``."""
    collector = _Collector(analysis, name)
    collector.find()
    return collector.found


def identity(project, occurrence):
    """Keys of the symbols ``occurrence`` finally denotes (imports followed). A
    symbol bound in source is a name in a scope (or an attribute of a class),
    whichever of its bindings reaches the occurrence."""
    targets = _Follower(project).follow(occurrence.goto())
    keys = set()
    describer = _Describer(project)
    for target in targets:
        if isinstance(target, inference.BindingEntity):
            target = target.binding
        bindings = target.bindings if isinstance(target, inference.AttributeEntity) \
            else [target]
        for binding in bindings:
            if isinstance(binding, scopes.Binding):
                owner = binding.details.get("owner")
                if owner is None and binding.scope.kind == scopes.Scope.CLASS:
                    owner = binding.scope
                if owner is not None:
                    keys.add(("attribute", id(owner), binding.name))
                else:
                    keys.add(("name", id(binding.scope), binding.name))
                continue
            for record in describer.targets([binding]):
                if record is not None:
                    keys.add(("definition", record["module_path"], record["line"],
                              record["column"], record["name"], record["full_name"]))
    return keys


def definition_sites(occurrence, project):
    """``(path, line, column)`` of the bindings ``occurrence`` refers to, directly
    or through imports."""
    targets = occurrence.goto()
    targets = targets + _Follower(project).follow(targets)
    sites = []
    for target in targets:
        if isinstance(target, inference.BindingEntity):
            target = target.binding
        bindings = target.bindings if isinstance(target, inference.AttributeEntity) \
            else [target]
        for binding in bindings:
            if isinstance(binding, scopes.Binding) and binding.form != scopes.STAR:
                sites.append((binding.home.tree.path,) + tuple(binding.position))
    return sites


def describer(project):
    """An object turning targets and values of ``project`` into definition records
    (``targets``, ``values``, ``binding``) and paths into project-relative ones
    (``relative``)."""
    return _Describer(project)


# ---------------------------------------------------------------------------
# Finding the identifier under the cursor

class _Occurrence:
    """One identifier in the main file and what it means."""

    def __init__(self, analysis, kind, node, scope, stmt, conditions=(), comprehension=None,
                 **extra):
        self.analysis = analysis
        self.kind = kind
        self.node = node
        self.scope = scope
        self.stmt = stmt
        self.conditions = list(conditions)  # narrowing from enclosing and/or/if-else
        self.comprehension = comprehension or {}  # visible comprehension variables
        self.extra = extra

    def where(self):
        if self.stmt is None:
            where = Where(self.scope)
        else:
            where = self.analysis.where_before(self.scope, self.stmt)
        if self.conditions:
            state = where.state if where.state is not None \
                else self.analysis.flow(self.scope).end
            where.state = state.narrowed(self.conditions)
        return self._with_comprehension(where, self.comprehension)

    def _with_comprehension(self, base, visible):
        if not visible:
            return base
        local = {name: self._comprehension_values(info, base) for name, info in visible.items()}
        return Where(base.scope, base.state, base.frame, local)

    def _comprehension_values(self, info, base):
        generator, _, path, before = info
        if path is None:
            return []
        where = self._with_comprehension(base, before)
        values = self.analysis.evaluate(generator.iter, where)
        return self.analysis.index_path([v for value in values for v in value.iterate()], path)

    # Results: goto gives targets (Bindings, Entities, value targets), infer values.
    def goto(self):
        return self._answer(GOTO)

    def is_definition(self):
        """Whether this identifier is where its name gets bound."""
        if self.kind in ("binding", "lambda"):
            return True
        return self.kind == "comprehension" and isinstance(getattr(self.node, "ctx", None),
                                                           ast.Store)

    def infer(self):
        return self._answer(INFER)

    def _answer(self, command):
        analysis = self.analysis
        kind = self.kind
        binding = self.extra.get("binding")
        if binding is not None:
            if command == GOTO:
                return [binding]
            return analysis.binding_values(binding)
        if kind == "name":
            return self._name(command, self.node.id, self.where())
        if kind == "global":
            module = self.scope
            while module.parent is not None:
                module = module.parent
            return self._name(command, self.extra["name"], Where(module))
        if kind == "attr":
            receivers = analysis.evaluate(self.node.value, self.where())
            result = []
            for receiver in receivers:
                if command == GOTO:
                    result.extend(receiver.attribute_targets(self.node.attr))
                else:
                    result.extend(receiver.attribute(self.node.attr))
            return result
        if kind == "module":
            found = analysis.project.module_value(self.extra["dotted"], self.extra["level"],
                                                  analysis.path)
            if found is None:
                return []
            return [inference.ValueTarget(found)] if command == GOTO else [found]
        if kind == "imported":
            import_binding = self.extra["import_binding"]
            if command == GOTO:
                targets = analysis.import_from_targets(import_binding)
                if targets:
                    return targets
                return [inference.ValueTarget(v)
                        for v in analysis.binding_values(import_binding)]
            return analysis.binding_values(import_binding)
        if kind == "keyword":
            params = self._keyword_params()
            if command == GOTO:
                return params
            return [v for p in params for v in analysis.binding_values(p)]
        if kind == "comprehension":
            info = self.comprehension[self.node.id]
            if command == GOTO:
                return [_ComprehensionTarget(self.analysis, info[0], info[1])]
            return self._comprehension_values(info, self.where())
        return []

    def _name(self, command, name, where):
        analysis = self.analysis
        if command == GOTO:
            return [target for target, _ in analysis.resolve(name, where)]
        return analysis.name_values(name, where)

    def _keyword_params(self):
        analysis = self.analysis
        name = self.node.arg
        functions = []
        for value in analysis.evaluate(self.extra["call"].func, self.where()):
            if isinstance(value, StaticFunction):
                functions.append(value)
            elif isinstance(value, StaticClass):
                functions.extend(v for v in value.attribute("__init__")
                                 if isinstance(v, StaticFunction))
        params = []
        for function in functions:
            params.extend(e for e in function.scope.events
                          if e.form == scopes.PARAM and e.name == name)
        return params


class _Follower:
    """Follows import bindings to the definitions they import."""

    def __init__(self, project):
        self.project = project

    def follow(self, targets):
        result = []
        for target in targets:
            followed = self._follow(target, set())
            result.extend(followed if followed is not None else [target])
        return result

    def _follow(self, target, seen):
        """Final targets for ``target``, or None when the chain is broken."""
        if isinstance(target, inference.BindingEntity):
            target = target.binding
        if isinstance(target, inference.ValueEntity):
            values = target.values()
            if not values:
                return None
            found = [self._follow(inference.ValueTarget(v), seen) for v in values]
            found = [t for group in found if group for t in group]
            return found or None
        if isinstance(target, inference.ValueTarget):
            return None if isinstance(target.value, RuntimeValue) else [target]
        if not isinstance(target, scopes.Binding) \
                or target.form not in (scopes.IMPORT, scopes.IMPORT_FROM):
            return [target]
        if id(target) in seen:
            return None
        seen = seen | {id(target)}
        details = target.details
        analysis = target.home.tree.analysis
        project = self.project
        if target.form == scopes.IMPORT:
            module = project.module_value(details["module"], 0, analysis.path)
            if isinstance(module, (StaticModule, DirectoryModule)):
                return [inference.ValueTarget(module)]
            return None
        module = project.module_value(details["module"], details["level"], analysis.path)
        if not isinstance(module, (StaticModule, DirectoryModule)):
            return None
        attr = details["attr"]
        inner = [t for t in module.attribute_targets(attr) if t is not target]
        if isinstance(module, StaticModule) and not inner:
            sub = None
            package = module.analysis.package_dir()
            if package:
                sub = project.submodule_value(package, attr)
            inner = [inference.ValueTarget(sub)] if sub is not None else []
        result = []
        for item in inner:
            found = self._follow(item, seen)
            if found:
                result.extend(found)
        return result or None


class _ComprehensionTarget:
    def __init__(self, analysis, generator, target):
        self.analysis = analysis
        self.generator = generator
        self.target = target


class _Finder:
    """Walks the main file's syntax tree looking for the cursor's identifier."""

    def __init__(self, analysis, line, col, named=False):
        self.named = named  # report (name, line, column, occurrence) instead
        self.analysis = analysis
        self.tree = analysis.tree
        self.line = line
        self.col = col
        self.exact = None
        self.touching = None
        self.conditions = []
        self.comprehension = {}
        self.bindings = {}
        for binding in _all_bindings(self.tree.module):
            if binding.node is not None:
                self.bindings.setdefault(id(binding.node), binding)

    def find(self):
        module = self.tree.module
        for statement in module.node.body:
            self._walk(statement, module, None, {})
        return self.exact or self.touching

    def _check(self, line, start, name, make):
        if line != self.line or name is None:
            return
        if self.named:
            make = (lambda make: lambda: (name, line, start, make()))(make)
        end = start + len(name)
        if start <= self.col < end:
            if self.exact is None:
                self.exact = make()
        elif self.col == end and self.touching is None:
            self.touching = make()

    def _occurrence(self, kind, node, scope, stmt, **extra):
        conditions = list(self.conditions)
        comprehension = self.comprehension
        return lambda: _Occurrence(self.analysis, kind, node, scope, stmt, conditions,
                                   comprehension, **extra)

    def _walk_narrowed(self, node, scope, stmt, comprehension, conditions):
        saved = self.conditions
        self.conditions = saved + list(conditions)
        try:
            self._walk(node, scope, stmt, comprehension)
        finally:
            self.conditions = saved

    def _bound(self, node, scope, stmt, fallback_kind="name"):
        binding = self.bindings.get(id(node))
        if binding is not None:
            return self._occurrence("binding", node, scope, stmt, binding=binding)
        return self._occurrence(fallback_kind, node, scope, stmt)

    def _walk(self, node, scope, stmt, comprehension):
        if node is None or not self._within(node):
            return
        saved = self.comprehension
        self.comprehension = comprehension
        try:
            self._visit(node, scope, stmt, comprehension)
        finally:
            self.comprehension = saved

    def _visit(self, node, scope, stmt, comprehension):
        if isinstance(node, (ast.stmt, ast.ExceptHandler, ast.match_case)):
            stmt = node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._function(node, scope, stmt)
        elif isinstance(node, ast.ClassDef):
            for child in node.decorator_list + node.bases:
                self._walk(child, scope, stmt, comprehension)
            for keyword in node.keywords:
                if keyword.arg is not None:
                    self._check(keyword.lineno, keyword.col_offset, keyword.arg,
                                self._occurrence("nothing", keyword, scope, stmt))
                self._walk(keyword.value, scope, stmt, comprehension)
            self._type_params(node, scope, stmt)
            line, col = self.tree.definition_position(node)
            self._check(line, col, node.name, self._bound(node, scope, stmt))
            inner = self.analysis.scope_of(node) or scope
            for child in node.body:
                self._walk(child, inner, child, {})
        elif isinstance(node, ast.Lambda):
            args = node.args
            for default in args.defaults + [d for d in args.kw_defaults if d is not None]:
                self._walk(default, scope, stmt, comprehension)
            for arg in _arguments(args):
                self._check(arg.lineno, arg.col_offset, arg.arg,
                            self._occurrence("lambda", arg, scope, stmt))
            shadowed = {k: v for k, v in comprehension.items()
                        if k not in {a.arg for a in _arguments(args)}}
            self._walk(node.body, scope, stmt, shadowed)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            self._comprehension(node, scope, stmt, comprehension)
        elif isinstance(node, ast.BoolOp):
            known = []
            for value in node.values:
                self._walk_narrowed(value, scope, stmt, comprehension, known)
                positive, negative = flow.conditions(value)
                known = known + (positive if isinstance(node.op, ast.And) else negative)
        elif isinstance(node, ast.IfExp):
            positive, negative = flow.conditions(node.test)
            self._walk(node.test, scope, stmt, comprehension)
            self._walk_narrowed(node.body, scope, stmt, comprehension, positive)
            self._walk_narrowed(node.orelse, scope, stmt, comprehension, negative)
        elif isinstance(node, ast.Name):
            if node.id in comprehension:
                make = self._occurrence("comprehension", node, scope, stmt)
            elif isinstance(node.ctx, ast.Store):
                make = self._bound(node, scope, stmt)
            else:
                make = self._occurrence("name", node, scope, stmt)
            self._check(node.lineno, node.col_offset, node.id, make)
        elif isinstance(node, ast.Attribute):
            self._walk(node.value, scope, stmt, comprehension)
            binding = self.bindings.get(id(node)) if isinstance(node.ctx, ast.Store) else None
            if binding is not None:
                make = self._occurrence("binding", node, scope, stmt, binding=binding)
            else:
                make = self._occurrence("attr", node, scope, stmt)
            self._check(node.end_lineno, node.end_col_offset - len(node.attr), node.attr, make)
        elif isinstance(node, ast.Call):
            self._walk(node.func, scope, stmt, comprehension)
            for arg in node.args:
                self._walk(arg, scope, stmt, comprehension)
            for keyword in node.keywords:
                if keyword.arg is not None:
                    self._check(keyword.lineno, keyword.col_offset, keyword.arg,
                                self._occurrence("keyword", keyword, scope, stmt, call=node))
                self._walk(keyword.value, scope, stmt, comprehension)
        elif isinstance(node, ast.Import):
            self._import(node, scope, stmt)
        elif isinstance(node, ast.ImportFrom):
            self._import_from(node, scope, stmt)
        elif isinstance(node, ast.ExceptHandler):
            self._walk(node.type, scope, stmt, comprehension)
            binding = self.bindings.get(id(node))
            if binding is not None:
                line, col = binding.position
                self._check(line, col, node.name, self._bound(node, scope, stmt))
            for child in node.body:
                self._walk(child, scope, child, comprehension)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            col = node.col_offset
            for name in node.names:
                line, col = self.tree.find_identifier(name, node.lineno, col)
                kind = "global" if isinstance(node, ast.Global) else "name"
                target = ast.Name(id=name, ctx=ast.Load())
                self._check(line, col, name,
                            self._occurrence(kind, target, scope, stmt, name=name))
        elif isinstance(node, (ast.MatchAs, ast.MatchStar, ast.MatchMapping)):
            for child in ast.iter_child_nodes(node):
                self._walk(child, scope, stmt, comprehension)
            binding = self.bindings.get(id(node))
            if binding is not None:
                line, col = binding.position
                self._check(line, col, binding.name, self._bound(node, scope, stmt))
        else:
            for child in ast.iter_child_nodes(node):
                self._walk(child, scope, stmt, comprehension)

    def _within(self, node):
        first = getattr(node, "lineno", None)
        if first is None:
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and node.decorator_list:
            first = min(first, min(d.lineno for d in node.decorator_list))
        last = getattr(node, "end_lineno", None) or first
        return first <= self.line <= last

    def _type_params(self, node, scope, stmt):
        for param in getattr(node, "type_params", None) or ():
            name = getattr(param, "name", None)
            if name:
                self._check(param.lineno, param.col_offset + _type_param_prefix(param), name,
                            self._occurrence("nothing", param, scope, stmt))

    def _function(self, node, scope, stmt):
        for child in node.decorator_list:
            self._walk(child, scope, stmt, {})
        self._type_params(node, scope, stmt)
        args = node.args
        for default in args.defaults + [d for d in args.kw_defaults if d is not None]:
            self._walk(default, scope, stmt, {})
        inner = self.analysis.scope_of(node) or scope
        for arg in _arguments(args):
            self._walk(arg.annotation, scope, stmt, {})
            self._check(arg.lineno, arg.col_offset, arg.arg, self._bound(arg, inner, stmt))
        self._walk(node.returns, scope, stmt, {})
        line, col = self.tree.definition_position(node)
        self._check(line, col, node.name, self._bound(node, scope, stmt))
        for child in node.body:
            self._walk(child, inner, child, {})

    def _comprehension(self, node, scope, stmt, comprehension):
        visible = dict(comprehension)
        for generator in node.generators:
            self._walk(generator.iter, scope, stmt, visible)
            before = dict(visible)
            for name_node, path in _target_names(generator.target):
                visible[name_node.id] = (generator, name_node, path, before)
            self._walk(generator.target, scope, stmt, visible)
            for condition in generator.ifs:
                self._walk(condition, scope, stmt, visible)
        if isinstance(node, ast.DictComp):
            self._walk(node.key, scope, stmt, visible)
            self._walk(node.value, scope, stmt, visible)
        else:
            self._walk(node.elt, scope, stmt, visible)

    def _import(self, node, scope, stmt):
        for alias in node.names:
            binding = self.bindings.get(id(alias))
            parts = alias.name.split(".")
            col = alias.col_offset
            for index, part in enumerate(parts):
                dotted = ".".join(parts[: index + 1])
                if index == 0 and not alias.asname and binding is not None:
                    make = self._occurrence("binding", alias, scope, stmt, binding=binding)
                else:
                    make = self._occurrence("module", alias, scope, stmt, dotted=dotted, level=0)
                self._check(alias.lineno, col, part, make)
                col += len(part) + 1
            if alias.asname and binding is not None:
                line, col = binding.position
                self._check(line, col, alias.asname,
                            self._occurrence("binding", alias, scope, stmt, binding=binding))

    def _import_from(self, node, scope, stmt):
        if node.module:
            line, col = _module_position(self.tree, node)
            parts = node.module.split(".")
            for index, part in enumerate(parts):
                dotted = ".".join(parts[: index + 1])
                self._check(line, col, part, self._occurrence(
                    "module", node, scope, stmt, dotted=dotted, level=node.level))
                col += len(part) + 1
        for alias in node.names:
            binding = self.bindings.get(id(alias))
            if binding is None:
                continue
            if alias.asname:
                self._check(alias.lineno, alias.col_offset, alias.name, self._occurrence(
                    "imported", alias, scope, stmt, import_binding=binding))
                line, col = binding.position
                self._check(line, col, alias.asname,
                            self._occurrence("binding", alias, scope, stmt, binding=binding))
            else:
                self._check(alias.lineno, alias.col_offset, alias.name,
                            self._occurrence("binding", alias, scope, stmt, binding=binding))


class _Collector(_Finder):
    """Finds every identifier spelled a given way."""

    def __init__(self, analysis, name):
        _Finder.__init__(self, analysis, 0, 0)
        self.name = name
        self.found = []

    def _check(self, line, start, name, make):
        if name == self.name:
            self.found.append((line, start, make()))

    def _within(self, node):
        return True


def _type_param_prefix(param):
    """Width of the ``*``/``**`` before a type parameter's name."""
    if param.__class__.__name__ == "TypeVarTuple":
        return 1
    if param.__class__.__name__ == "ParamSpec":
        return 2
    return 0


def _module_position(tree, node):
    """Position of the module name in ``from <module> import ...``."""
    for number in range(node.lineno, (node.end_lineno or node.lineno) + 1):
        text = tree.line_text(number)
        start = node.col_offset if number == node.lineno else 0
        match = re.compile(r"\bfrom\s*\.*\s*").search(text, start)
        if match:
            return number, match.end()
    return node.lineno, node.col_offset


def _arguments(args):
    found = args.posonlyargs + args.args
    if args.vararg:
        found.append(args.vararg)
    found += args.kwonlyargs
    if args.kwarg:
        found.append(args.kwarg)
    return found


def _target_names(target, path=()):
    if isinstance(target, ast.Name):
        yield target, path
    elif isinstance(target, (ast.Tuple, ast.List)):
        for index, element in enumerate(target.elts):
            if isinstance(element, ast.Starred):
                for name, _ in _target_names(element.value):
                    yield name, None
            else:
                yield from _target_names(element, path + (index,))


def _all_bindings(scope):
    yield from scope.events
    yield from scope.instance_events
    for child in scope.children:
        yield from _all_bindings(child)


# ---------------------------------------------------------------------------
# Describing definitions

class _Describer:
    def __init__(self, project):
        self.project = project
        self.root = project.root

    # -- entry points ----------------------------------------------------
    def targets(self, targets):
        records = []
        for target in targets:
            if isinstance(target, scopes.Binding):
                records.append(self.binding(target))
            elif isinstance(target, inference.BindingEntity):
                records.append(self.binding(target.binding))
            elif isinstance(target, inference.AttributeEntity):
                records.extend(self.binding(b) for b in target.bindings)
            elif isinstance(target, RuntimeEntity):
                records.append(self.runtime_entity(target))
            elif isinstance(target, inference.ValueEntity):
                records.extend(self.value(v) for v in target.values())
            elif isinstance(target, inference.ValueTarget):
                records.append(self.value(target.value))
            elif isinstance(target, _ComprehensionTarget):
                records.append(self.comprehension(target))
        return records

    def values(self, values):
        return [self.value(value) for value in values]

    # -- helpers ---------------------------------------------------------
    def relative(self, path):
        if not path:
            return ""
        path = os.path.abspath(path)
        try:
            relative = os.path.relpath(path, self.root)
        except ValueError:  # another drive (Windows)
            relative = path
        if relative.startswith(os.pardir + os.sep) or relative == os.pardir:
            relative = path
        return relative.replace(os.sep, "/")

    def module_name(self, path):
        relative = self.relative(path)
        if os.path.isabs(relative):
            relative = os.path.basename(relative)
        if relative.endswith(".pyi"):
            relative = relative[:-4]
            if relative.startswith("stubs/"):
                relative = relative[len("stubs/"):]
        elif relative.endswith(".py"):
            relative = relative[:-3]
        parts = [p for p in relative.split("/") if p]
        if len(parts) > 1 and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    def directory_name(self, directory):
        return ".".join(p for p in self.relative(directory).split("/") if p)

    def relative_import_name(self, importer, dotted, level):
        """Qualified name of ``<level dots><dotted>`` imported from ``importer``."""
        if not level:
            return dotted
        parts = self.module_name(importer).split(".")
        drop = level - 1 if os.path.basename(importer) == "__init__.py" else level
        parts = parts[: max(0, len(parts) - drop)] if drop <= len(parts) else []
        return ".".join(p for p in parts + [dotted] if p)

    def qualified(self, scope, name=None):
        names = []
        while scope is not None and scope.parent is not None:
            names.append(scope.name)
            scope = scope.parent
        tree = scope.tree if scope is not None else None
        prefix = [self.module_name(tree.path)] if tree is not None and tree.path else []
        result = prefix + list(reversed(names))
        if name is not None:
            result.append(name)
        return ".".join(p for p in result if p)

    @staticmethod
    def record(name, kind, full_name, module_path, line, column, description, docstring):
        return {"name": name, "type": kind, "full_name": full_name,
                "module_path": module_path, "line": line, "column": column,
                "description": description, "docstring": docstring or ""}

    # -- source definitions ----------------------------------------------
    def binding(self, binding):
        form = binding.form
        tree = binding.home.tree
        line, column = binding.position
        module_path = self.relative(tree.path)
        if form in (scopes.DEF, scopes.CLASS):
            scope = tree.analysis.scope_of(binding.node)
            if scope is not None:
                return self.scope_definition(scope)
        owner = binding.details.get("owner")
        if owner is not None:
            full_name = self.qualified(owner, binding.name)
        else:
            full_name = self.qualified(binding.scope, binding.name)
        if form == scopes.PARAM:
            return self.record(binding.name, "param", full_name, module_path, line, column,
                               "param %s" % binding.name, "")
        if form in (scopes.IMPORT, scopes.IMPORT_FROM):
            return self.import_binding(binding, module_path, line, column)
        return self.record(binding.name, "statement", full_name, module_path, line, column,
                           _statement_description(tree, binding), "")

    def import_binding(self, binding, module_path, line, column):
        analysis = binding.home.tree.analysis
        details = binding.details
        values = analysis.binding_values(binding)
        kind = "module"
        full_name = None
        if binding.form == scopes.IMPORT:
            full_name = details["module"]
        else:
            for value in values:
                if value.kind in (inference.MODULE, inference.CLASS, inference.FUNCTION,
                                  inference.INSTANCE):
                    kind = value.kind
                    break
            module = analysis.project.module_value(details["module"], details["level"],
                                                   analysis.path)
            prefix = None
            if isinstance(module, StaticModule):
                prefix = self.module_name(module.analysis.path)
            elif isinstance(module, DirectoryModule):
                prefix = self.directory_name(module.directory)
            elif isinstance(module, RuntimeValue):
                prefix = getattr(module.obj, "__name__", None)
            if not prefix:
                prefix = self.relative_import_name(analysis.path, details["module"] or "",
                                                   details["level"])
            full_name = "%s.%s" % (prefix, details["attr"]) if prefix else details["attr"]
        description = _import_text(binding.home.tree, binding.stmt)
        return self.record(binding.name, kind, full_name, module_path, line, column,
                           description, "")

    def scope_definition(self, scope, instance=False):
        node = scope.node
        tree = scope.tree
        line, column = tree.definition_position(node)
        full_name = self.qualified(scope)
        docstring = _docstring(node)
        module_path = self.relative(tree.path)
        if isinstance(node, ast.ClassDef):
            if instance:
                return self.record(node.name, "instance", full_name, module_path, line,
                                   column, "instance of %s" % node.name, docstring)
            return self.record(node.name, "class", full_name, module_path, line, column,
                               "class %s" % node.name, docstring)
        return self.record(node.name, "function", full_name, module_path, line, column,
                           "def %s(%s)" % (node.name, _parameters(node)), docstring)

    def comprehension(self, target):
        tree = target.analysis.tree
        node = target.target
        generator = target.generator
        description = "for %s in %s" % (_text(tree, generator.target),
                                        _text(tree, generator.iter))
        return self.record(node.id, "statement", self.qualified(tree.module, node.id),
                           self.relative(tree.path), node.lineno, node.col_offset,
                           description, "")

    # -- values ----------------------------------------------------------
    def value(self, value):
        if isinstance(value, StaticInstance):
            return self.scope_definition(value.cls.scope, instance=True)
        if isinstance(value, (StaticClass, StaticFunction)):
            return self.scope_definition(value.scope)
        if isinstance(value, StaticModule):
            path = value.analysis.path
            full_name = self.module_name(path)
            module = value.analysis.tree.module.node
            return self.record(full_name.split(".")[-1], "module", full_name,
                               self.relative(path), 1, 0, "module %s" % full_name.split(".")[-1],
                               _docstring(module))
        if isinstance(value, DirectoryModule):
            full_name = self.directory_name(value.directory)
            name = full_name.split(".")[-1]
            return self.record(name, "module", full_name, self.relative(value.directory),
                               0, 0, "module %s" % name, "")
        if isinstance(value, (RuntimeInstance, DictInstance)):
            return self.runtime_instance(value.cls)
        if isinstance(value, RuntimeValue):
            return self.runtime_object(value.obj)
        if isinstance(value, inference._DictView):
            return self.runtime_object(getattr(dict, value.which))
        return None

    def runtime_instance(self, cls):
        name = _type_name(cls)
        return self.record(name, "instance", "%s.%s" % (_type_module(cls), name), "", 0, 0,
                           "instance of %s" % name, "")

    def runtime_object(self, obj, name=None, full_name=None):
        kind = introspect.kind_of(obj)
        if kind == inference.INSTANCE:
            return self.runtime_instance(type(obj))
        if kind == inference.MODULE:
            module_name = getattr(obj, "__name__", name or "")
            short = module_name.split(".")[-1]
            return self.record(name or short, "module", module_name, "", 0, 0,
                               "module %s" % (name or short), "")
        if kind == inference.CLASS:
            own = _type_name(obj)
            full = full_name or "%s.%s" % (_type_module(obj),
                                           getattr(obj, "__qualname__", own))
            return self.record(name or own, "class", full, "", 0, 0,
                               "class %s" % (name or own), "")
        own = getattr(obj, "__name__", name or "")
        if full_name is None:
            module = getattr(obj, "__module__", None)
            qualname = getattr(obj, "__qualname__", own)
            if module is None:
                owner = getattr(obj, "__objclass__", None) or getattr(obj, "__self__", None)
                if owner is not None and not isinstance(owner, (type, types.ModuleType)):
                    owner = type(owner)
                module = getattr(owner, "__module__", None)
            full_name = "%s.%s" % (module, qualname) if module else qualname
        name = name or own
        return self.record(name, "function", full_name, "", 0, 0,
                           "def %s(%s)" % (name, _runtime_parameters(obj)), "")

    def runtime_entity(self, entity):
        ok, obj = entity.fetch()
        if not ok:
            return None
        full_name = "%s.%s" % (entity.owner_name(), entity.name)
        kind = introspect.kind_of(obj)
        if kind == inference.INSTANCE:
            if obj is None or isinstance(obj, (bool, int, float, str, bytes)):
                return self.runtime_instance(type(obj))
            name = _type_name(type(obj))
            return self.record(entity.name, "instance", full_name, "", 0, 0,
                               "instance of %s" % name, "")
        if kind == inference.MODULE:
            return self.runtime_object(obj, name=entity.name)
        return self.runtime_object(obj, name=entity.name, full_name=full_name)


def _type_name(cls):
    if cls is type(None):
        return "None"
    return getattr(cls, "__name__", "object")


def _type_module(cls):
    module = getattr(cls, "__module__", None) or "builtins"
    if cls in (type(None), types.GeneratorType, type(Ellipsis), type(NotImplemented)):
        return "builtins"
    return module


def _docstring(node):
    try:
        return ast.get_docstring(node, clean=True) or ""
    except (TypeError, AttributeError):
        return ""


def _parameters(node):
    try:
        return ast.unparse(node.args)
    except Exception:  # unparse may choke on repaired or odd trees
        return ", ".join(a.arg for a in _arguments(node.args))


def _runtime_parameters(obj):
    try:
        signature = inspect.signature(obj)
    except (TypeError, ValueError):
        return "..."
    text = str(signature)
    return text[1:text.rfind(")")] if text.startswith("(") else "..."


def _collapse(text):
    return re.sub(r"\s+", " ", text).strip()


def _text(tree, node):
    segment = tree.segment(node)
    if segment is None:
        try:
            segment = ast.unparse(node)
        except Exception:  # odd trees
            segment = ""
    return _collapse(segment)


def _import_text(tree, statement):
    if statement is None:
        return ""
    segment = tree.segment(statement)
    if segment is None or "\n" in segment:
        try:
            return ast.unparse(statement)
        except Exception:  # odd trees
            return _collapse(segment or "")
    return _collapse(segment)


def _statement_description(tree, binding):
    details = binding.details
    statement = binding.stmt
    if binding.form == scopes.ASSIGN and details.get("value") is not None:
        return _text(tree, details["value"])
    if statement is None:
        return binding.name
    if isinstance(statement, (ast.AnnAssign, ast.AugAssign, ast.Assign, ast.Expr)):
        return _text(tree, statement)
    if isinstance(statement, (ast.For, ast.AsyncFor)):
        return "for %s in %s" % (_text(tree, statement.target), _text(tree, statement.iter))
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        return "with " + ", ".join(_text(tree, item.context_expr) + (
            " as " + _text(tree, item.optional_vars) if item.optional_vars else "")
            for item in statement.items)
    if isinstance(statement, ast.ExceptHandler):
        text = "except"
        if statement.type is not None:
            text += " " + _text(tree, statement.type)
        return text + (" as %s" % statement.name if statement.name else "")
    if isinstance(statement, ast.match_case):
        return "case " + _text(tree, statement.pattern)
    first = tree.line_text(statement.lineno)[statement.col_offset:]
    return _collapse(first).rstrip(":")
