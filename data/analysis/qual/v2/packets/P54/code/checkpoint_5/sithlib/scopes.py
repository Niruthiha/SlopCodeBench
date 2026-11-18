"""Scope and binding model.

Secret: how name bindings are discovered in a syntax tree, which scope they
belong to, and the rules (indentation heuristics included) that decide which
scope encloses a cursor and which bindings are visible from it.
"""

import ast
import re

from . import parsing

# Binding forms exposed to clients.
DEF = "def"
CLASS = "class"
PARAM = "param"
ASSIGN = "assign"
IMPORT = "import"
IMPORT_FROM = "import_from"
STAR = "star"
EXCEPT = "except"
OTHER = "other"


class Binding:
    """One event that binds a name (or, for STAR, a set of names)."""

    def __init__(self, name, form, line, order, scope, node=None, position=None,
                 stmt=None, home=None, **details):
        self.name = name
        self.form = form
        self.line = line
        self.order = order
        self.scope = scope
        # where the bound identifier itself is written: (1-based line, 0-based column)
        self.position = position or (line, 0)
        # the syntax node naming the binding, the statement (or handler/case)
        # that performs it, and the scope whose code contains that statement
        self.node = node
        self.stmt = stmt
        self.home = home or scope
        # form-specific details:
        #   DEF/CLASS: node
        #   PARAM: function (Scope), index, annotation, default, star ("", "*", "**"),
        #          keyword_only (optional)
        #   ASSIGN: value (expr or None), path (tuple of ints), annotation,
        #           owner (class Scope, for instance attributes), starred
        #   OTHER: source ("for"/"with"/None), value (iterable/context expr), path
        #   IMPORT: module (dotted name bound), as_name (bool)
        #   IMPORT_FROM: module, level, attr
        #   STAR: module, level
        #   EXCEPT: type_expr
        self.details = details


class Scope:
    MODULE, FUNCTION, CLASS = "module", "function", "class"

    def __init__(self, kind, node, parent, tree):
        self.kind = kind
        self.node = node
        self.parent = parent
        self.tree = tree
        self.children = []
        self.events = []
        self.instance_events = []  # self.<attr> assignments in methods (classes)
        self.globals_declared = set()

    @property
    def name(self):
        return getattr(self.node, "name", None)

    def class_scope(self):
        """For a method, the scope of the class that defines it."""
        if self.kind == Scope.FUNCTION and self.parent is not None \
                and self.parent.kind == Scope.CLASS:
            return self.parent
        return None

    def decorator_names(self):
        names = []
        for deco in getattr(self.node, "decorator_list", []):
            if isinstance(deco, ast.Name):
                names.append(deco.id)
            elif isinstance(deco, ast.Attribute):
                names.append(deco.attr)
        return names

    def returned_expressions(self):
        """Return-value expressions of a function (excluding nested scopes)."""
        found = []
        for node in _walk_own(self.node.body if self.node is not None else []):
            if isinstance(node, (ast.Yield, ast.YieldFrom)):
                return []
            if isinstance(node, ast.Return) and node.value is not None:
                found.append(node.value)
        return found

    def return_statements(self):
        """``return`` statements of a function, or None for generators."""
        found = []
        for node in _walk_own(self.node.body if self.node is not None else []):
            if isinstance(node, (ast.Yield, ast.YieldFrom)):
                return None
            if isinstance(node, ast.Return):
                found.append(node)
        return found

    def base_expressions(self):
        return list(getattr(self.node, "bases", []))

    def is_async(self):
        return isinstance(self.node, ast.AsyncFunctionDef)

    def chain(self):
        """Scopes searched for names from here: self, enclosing functions, module."""
        result = [self]
        scope = self.parent
        while scope is not None:
            if scope.kind != Scope.CLASS:
                result.append(scope)
            scope = scope.parent
        return result

    def events_until_line(self, line):
        return [e for e in self.events if e.line <= line]

    def events_before(self, order):
        return [e for e in self.events if e.order < order]

    def all_events(self):
        return list(self.events)

    def instance_attribute_events(self):
        return list(self.instance_events)


class ScopeTree:
    def __init__(self, text, path=None):
        self.path = path
        self._lines = text.split("\n")
        module = parsing.parse_tolerant(text)
        self.module = Scope(Scope.MODULE, module, None, self)
        _Collector(self.module).visit_body(module.body)

    def line_text(self, line):
        return self._lines[line - 1] if 0 < line <= len(self._lines) else ""

    def segment(self, node):
        """Source text of ``node`` (as written), or None."""
        try:
            first, last = node.lineno, node.end_lineno
            if last is None or first > len(self._lines):
                return None
            if first == last:
                return self._lines[first - 1][node.col_offset:node.end_col_offset]
            parts = [self._lines[first - 1][node.col_offset:]]
            parts.extend(self._lines[first:last - 1])
            parts.append(self._lines[last - 1][:node.end_col_offset])
            return "\n".join(parts)
        except (AttributeError, IndexError, TypeError):
            return None

    def find_identifier(self, name, line, col, after_keyword=None):
        """Position of identifier ``name`` at or after (line, col).

        With ``after_keyword`` the identifier must follow that keyword.
        """
        pattern = re.compile((r"\b%s\s+" % after_keyword if after_keyword else r"(?<![\w.])")
                             + r"(%s)\b" % re.escape(name))
        for number in range(line, min(line + 50, len(self._lines)) + 1):
            text = self._lines[number - 1]
            start = col if number == line else 0
            match = pattern.search(text, start)
            if match:
                return number, match.start(1)
        return line, col

    def definition_position(self, node):
        """Position of the name in a ``def``/``class`` header."""
        keyword = "class" if isinstance(node, ast.ClassDef) else "def"
        return self.find_identifier(node.name, node.lineno, node.col_offset, keyword)

    def scope_at(self, line, col):
        scope = self.module
        while True:
            inner = None
            for child in scope.children:
                if self._contains(child, line, col):
                    inner = child
            if inner is None:
                return scope
            scope = inner

    def _contains(self, scope, line, col):
        node = scope.node
        header, end = node.lineno, node.end_lineno or node.lineno
        header_col = node.col_offset
        body = node.body[0] if node.body else None
        if line < header:
            return False
        if line == header:
            return body is not None and body.lineno == header and col >= body.col_offset
        text = self._lines[line - 1] if line - 1 < len(self._lines) else ""
        before = text[:col]
        indent = _indent_width(text) if before.strip() else col
        if indent <= header_col and (line > end or not before.strip()):
            return False
        if line <= end:
            return True
        for number in range(end + 1, line):
            other = self._lines[number - 1] if number - 1 < len(self._lines) else ""
            stripped = other.strip()
            if stripped and not stripped.startswith("#") and _indent_width(other) <= header_col:
                return False
        return True


def _indent_width(text):
    return len(text) - len(text.lstrip())


def _walk_own(statements):
    """Walk nodes in ``statements`` without entering nested scopes."""
    stack = list(reversed(statements))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


class _Counter:
    value = 0

    @classmethod
    def next(cls):
        cls.value += 1
        return cls.value


class _Collector(ast.NodeVisitor):
    def __init__(self, scope):
        self.scope = scope
        self.stmt = None

    def visit(self, node):
        if isinstance(node, (ast.stmt, ast.ExceptHandler, ast.match_case)):
            saved, self.stmt = self.stmt, node
            try:
                return super().visit(node)
            finally:
                self.stmt = saved
        return super().visit(node)

    # -- helpers ---------------------------------------------------------
    def visit_body(self, statements):
        for statement in statements:
            self.visit(statement)

    def _target_scope(self, name):
        if name in self.scope.globals_declared:
            scope = self.scope
            while scope.parent is not None:
                scope = scope.parent
            return scope
        return self.scope

    def bind(self, name, form, line, node=None, position=None, **details):
        scope = self._target_scope(name) if name else self.scope
        binding = Binding(name, form, line, _Counter.next(), scope, node=node,
                          position=position, stmt=self.stmt, home=self.scope, **details)
        scope.events.append(binding)
        return binding

    def bind_target(self, target, line, value, path=(), annotation=None, starred=False):
        if isinstance(target, ast.Name):
            self.bind(target.id, ASSIGN, line, node=target, position=_start(target),
                      value=value, path=path, annotation=annotation, starred=starred)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for index, element in enumerate(target.elts):
                self.bind_target(element, line, value, path + (index,))
        elif isinstance(target, ast.Starred):
            self.bind_target(target.value, line, None, starred=True)
        else:
            self.visit(target)

    def bind_plain(self, target, line, source=None, value=None, path=()):
        if isinstance(target, ast.Name):
            self.bind(target.id, OTHER, line, node=target, position=_start(target),
                      source=source, value=value, path=path)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for index, element in enumerate(target.elts):
                self.bind_plain(element, line, source, value, path + (index,))
        elif isinstance(target, ast.Starred):
            self.bind_plain(target.value, line)
        else:
            for node in ast.walk(target):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    self.bind(node.id, OTHER, line, node=node, position=_start(node))

    # -- scopes ----------------------------------------------------------
    def _visit_function(self, node):
        for deco in node.decorator_list:
            self.visit(deco)
        args = node.args
        for default in args.defaults + [d for d in args.kw_defaults if d is not None]:
            self.visit(default)
        tree = self.scope.tree
        self.bind(node.name, DEF, node.lineno, node=node,
                  position=tree.definition_position(node))
        child = Scope(Scope.FUNCTION, node, self.scope, tree)
        self.scope.children.append(child)
        positional = args.posonlyargs + args.args
        defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
        index = 0
        for arg, default in zip(positional, defaults):
            child_bind(child, arg, node, function=child, index=index,
                       annotation=arg.annotation, default=default, star="")
            index += 1
        if args.vararg:
            child_bind(child, args.vararg, node, function=child, index=index,
                       annotation=None, default=None, star="*")
            index += 1
        for arg, default in zip(args.kwonlyargs, args.kw_defaults):
            child_bind(child, arg, node, function=child, index=index,
                       annotation=arg.annotation, default=default, star="", keyword_only=True)
            index += 1
        if args.kwarg:
            child_bind(child, args.kwarg, node, function=child, index=index,
                       annotation=None, default=None, star="**")
        collector = _Collector(child)
        for statement in _walk_own(node.body):
            if isinstance(statement, ast.Global):
                child.globals_declared.update(statement.names)
        collector.visit_body(node.body)
        parent_class = child.class_scope()
        if parent_class is not None and positional:
            decorators = child.decorator_names()
            if "staticmethod" not in decorators and "classmethod" not in decorators:
                self_name = positional[0].arg
                _collect_instance_attributes(parent_class, child, node.body, self_name,
                                             initializer=node.name == "__init__")

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_ClassDef(self, node):
        for deco in node.decorator_list:
            self.visit(deco)
        for base in node.bases:
            self.visit(base)
        tree = self.scope.tree
        self.bind(node.name, CLASS, node.lineno, node=node,
                  position=tree.definition_position(node))
        child = Scope(Scope.CLASS, node, self.scope, tree)
        self.scope.children.append(child)
        _Collector(child).visit_body(node.body)

    def visit_Lambda(self, node):
        pass

    def _visit_comprehension(self, node):
        for generator in node.generators:
            self.visit(generator.iter)
            break

    visit_ListComp = _visit_comprehension
    visit_SetComp = _visit_comprehension
    visit_DictComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension

    # -- statements ------------------------------------------------------
    def visit_Global(self, node):
        self.scope.globals_declared.update(node.names)

    def visit_Assign(self, node):
        self.visit(node.value)
        for target in node.targets:
            self.bind_target(target, node.lineno, node.value)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.visit(node.value)
        if isinstance(node.target, ast.Name):
            self.bind(node.target.id, ASSIGN, node.lineno, node=node.target,
                      position=_start(node.target), value=node.value, path=(),
                      annotation=node.annotation)
        else:
            self.visit(node.target)

    def visit_AugAssign(self, node):
        self.visit(node.value)
        if isinstance(node.target, ast.Name):
            name = node.target.id
            scope = self._target_scope(name)
            if not any(e.name == name for e in scope.events):
                self.bind(name, OTHER, node.lineno, node=node.target,
                          position=_start(node.target))
        else:
            self.visit(node.target)

    def visit_NamedExpr(self, node):
        self.visit(node.value)
        if isinstance(node.target, ast.Name):
            self.bind(node.target.id, ASSIGN, node.lineno, node=node.target,
                      position=_start(node.target), value=node.value, path=(),
                      annotation=None)

    def _visit_for(self, node):
        self.visit(node.iter)
        self.bind_plain(node.target, node.lineno, "for", node.iter)
        self.visit_body(node.body)
        self.visit_body(node.orelse)

    visit_For = _visit_for
    visit_AsyncFor = _visit_for

    def _visit_with(self, node):
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.bind_plain(item.optional_vars, node.lineno, "with", item.context_expr)
        self.visit_body(node.body)

    visit_With = _visit_with
    visit_AsyncWith = _visit_with

    def visit_ExceptHandler(self, node):
        if node.type is not None:
            self.visit(node.type)
        if node.name:
            tree = self.scope.tree
            position = tree.find_identifier(node.name, node.lineno, node.col_offset, "as")
            self.bind(node.name, EXCEPT, node.lineno, node=node, position=position,
                      type_expr=node.type)
        self.visit_body(node.body)

    def visit_Import(self, node):
        for alias in node.names:
            if alias.asname:
                self.bind(alias.asname, IMPORT, node.lineno, node=alias,
                          position=_as_position(alias), module=alias.name, as_name=True)
            else:
                first = alias.name.split(".")[0]
                self.bind(first, IMPORT, node.lineno, node=alias, position=_start(alias),
                          module=first, as_name=False)

    def visit_ImportFrom(self, node):
        module = node.module or ""
        for alias in node.names:
            if alias.name == "*":
                self.bind(None, STAR, node.lineno, node=alias, module=module, level=node.level)
            else:
                position = _as_position(alias) if alias.asname else _start(alias)
                self.bind(alias.asname or alias.name, IMPORT_FROM, node.lineno, node=alias,
                          position=position, module=module, level=node.level, attr=alias.name)

    def visit_MatchAs(self, node):
        if node.pattern is not None:
            self.visit(node.pattern)
        if node.name:
            position = (node.end_lineno, node.end_col_offset - len(node.name))
            self.bind(node.name, OTHER, node.lineno, node=node, position=position)

    def visit_MatchStar(self, node):
        if node.name:
            position = (node.end_lineno, node.end_col_offset - len(node.name))
            self.bind(node.name, OTHER, node.lineno, node=node, position=position)

    def visit_MatchMapping(self, node):
        self.generic_visit(node)
        if node.rest:
            position = self.scope.tree.find_identifier(node.rest, node.lineno, node.col_offset)
            self.bind(node.rest, OTHER, node.lineno, node=node, position=position)

    def visit_TypeAlias(self, node):
        if isinstance(node.name, ast.Name):
            self.bind(node.name.id, OTHER, node.lineno, node=node.name,
                      position=_start(node.name))


def _start(node):
    return (getattr(node, "lineno", 1), getattr(node, "col_offset", 0))


def _as_position(alias):
    """Position of the ``as`` name of an import alias."""
    return (alias.end_lineno, alias.end_col_offset - len(alias.asname))


def child_bind(scope, arg, function_node, **details):
    scope.events.append(Binding(arg.arg, PARAM, function_node.lineno, _Counter.next(), scope,
                                node=arg, position=_start(arg), stmt=function_node,
                                home=scope, **details))


def _collect_instance_attributes(class_scope, method_scope, body, self_name, initializer):
    """Record ``<self>.<attr> = ...`` assignments of a method on its class."""
    found = []

    def is_self_attr(target):
        return (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                and target.value.id == self_name)

    def record(target, statement, value, path, annotation=None):
        if is_self_attr(target):
            found.append(Binding(
                target.attr, ASSIGN, statement.lineno, _Counter.next(), method_scope,
                node=target, position=(target.end_lineno,
                                       target.end_col_offset - len(target.attr)),
                stmt=statement, home=method_scope, value=value, path=path,
                annotation=annotation, owner=class_scope))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for index, element in enumerate(target.elts):
                record(element, statement, value, path + (index,))
        elif isinstance(target, ast.Starred):
            record(target.value, statement, None, ())

    for node in _walk_own(body):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                record(target, node, node.value, ())
        elif isinstance(node, ast.AnnAssign):
            record(node.target, node, node.value, (), node.annotation)
        elif isinstance(node, ast.AugAssign) and is_self_attr(node.target):
            if not any(e.name == node.target.attr for e in class_scope.instance_events + found):
                target = node.target
                found.append(Binding(
                    target.attr, OTHER, node.lineno, _Counter.next(), method_scope,
                    node=target, position=(target.end_lineno,
                                           target.end_col_offset - len(target.attr)),
                    stmt=node, home=method_scope, owner=class_scope))
    if initializer:
        class_scope.instance_events[:0] = found
    else:
        class_scope.instance_events.extend(found)
