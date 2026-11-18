"""Scope analysis: which names each scope binds, and where."""
import ast
from dataclasses import dataclass, field

from .parsing import PLACEHOLDER

MODULE = "module"
FUNCTION = "function"
CLASS = "class"
LAMBDA = "lambda"
COMPREHENSION = "comprehension"

_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_COMPREHENSION_NODES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


@dataclass(eq=False)
class Binding:
    """A single place where a name is bound."""

    name: str
    line: int
    kind: str
    node: ast.AST
    scope: "Scope"
    value: ast.AST = None
    extra: dict = field(default_factory=dict)
    # The node naming the bound identifier (ast.Name, ast.arg, ast.alias, ...).
    target: ast.AST = None


@dataclass(eq=False)
class StarImport:
    """A `from module import *` statement."""

    module: str
    level: int
    line: int
    scope: "Scope"
    node: ast.AST = None


class Scope:
    """A namespace: module, function, class, lambda or comprehension."""

    def __init__(self, kind, node, parent, module):
        self.kind = kind
        self.node = node
        self.parent = parent
        self.module = module
        self.bindings = {}
        self.star_imports = []
        self.children = []
        self.global_names = set()
        self.local_node_ids = None  # ids of the nodes of the body, cached by flow analysis
        self.nonlocal_names = set()
        if parent is not None:
            parent.children.append(self)

    def add(self, binding):
        self.bindings.setdefault(binding.name, []).append(binding)

    def chain(self):
        """This scope followed by all its ancestors."""
        scope = self
        while scope is not None:
            yield scope
            scope = scope.parent

    def root(self):
        scope = self
        while scope.parent is not None:
            scope = scope.parent
        return scope


def iter_target_names(target, value):
    """Yield (Name node, value expression or None) pairs for an assignment target."""
    if isinstance(target, ast.Name):
        yield target, value
    elif isinstance(target, (ast.Tuple, ast.List)):
        values = None
        if (
            isinstance(value, (ast.Tuple, ast.List))
            and len(value.elts) == len(target.elts)
            and not any(isinstance(e, ast.Starred) for e in target.elts + value.elts)
        ):
            values = value.elts
        for index, element in enumerate(target.elts):
            yield from iter_target_names(element, values[index] if values else None)
    elif isinstance(target, ast.Starred):
        yield from iter_target_names(target.value, None)


def function_parameters(arguments):
    """All parameter `arg` nodes of an `ast.arguments`, in declaration order."""
    params = list(arguments.posonlyargs) + list(arguments.args)
    if arguments.vararg:
        params.append(arguments.vararg)
    params += list(arguments.kwonlyargs)
    if arguments.kwarg:
        params.append(arguments.kwarg)
    return params


def walk_local(statements):
    """Walk nodes of a body without descending into nested scopes."""
    stack = list(reversed(statements))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _FUNCTION_NODES + (ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _declared(statements, kind):
    """Names declared `global`/`nonlocal` directly in a function body."""
    names = set()
    stack = list(statements)
    while stack:
        node = stack.pop()
        if isinstance(node, kind):
            names.update(node.names)
        if isinstance(node, _FUNCTION_NODES + (ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return names


class ScopeBuilder:
    """Walks a module AST and builds its tree of scopes."""

    def __init__(self, module_context):
        self.module_context = module_context
        self.scope_by_node = {}
        self.binding_by_target = {}

    def build(self, tree):
        root = self._new_scope(MODULE, tree, None)
        self._statements(root, tree.body)
        return root

    def _new_scope(self, kind, node, parent):
        scope = Scope(kind, node, parent, self.module_context)
        self.scope_by_node[id(node)] = scope
        return scope

    # -- binding helpers -------------------------------------------------

    def _bind(self, scope, name, line, kind, node, value=None, target=None, **extra):
        if PLACEHOLDER in name:
            return
        if scope.kind == FUNCTION:
            if name in scope.nonlocal_names:
                return
            if name in scope.global_names:
                scope = scope.root()
        binding = Binding(name, line, kind, node, scope, value, extra, target)
        scope.add(binding)
        self.binding_by_target.setdefault(id(target if target is not None else node), binding)

    def _bind_target(self, scope, target, kind, value, node, **extra):
        for name_node, element_value in iter_target_names(target, value):
            self._bind(scope, name_node.id, name_node.lineno, kind, node, element_value,
                       target=name_node, **extra)
        for child in ast.walk(target):
            if isinstance(child, (ast.Attribute, ast.Subscript)):
                self._expression(scope, child)

    def _bind_arguments(self, scope, function_node):
        for index, param in enumerate(function_parameters(function_node.args)):
            self._bind(scope, param.arg, function_node.lineno, "param", function_node,
                       target=param, arg=param, index=index)

    # -- statements --------------------------------------------------------

    def _statements(self, scope, statements):
        for statement in statements:
            self._statement(scope, statement)

    def _statement(self, scope, node):
        handler = getattr(self, "_stmt_" + type(node).__name__, None)
        if handler is not None:
            handler(scope, node)
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                self._statement(scope, child)
            else:
                self._expression(scope, child)

    def _stmt_FunctionDef(self, scope, node):
        for expression in node.decorator_list + node.args.defaults + node.args.kw_defaults:
            self._expression(scope, expression)
        for param in function_parameters(node.args):
            self._expression(scope, param.annotation)
        self._expression(scope, node.returns)
        self._bind(scope, node.name, node.lineno, "def", node)
        child = self._new_scope(FUNCTION, node, scope)
        child.global_names = _declared(node.body, ast.Global)
        child.nonlocal_names = _declared(node.body, ast.Nonlocal)
        self._bind_arguments(child, node)
        self._statements(child, node.body)

    _stmt_AsyncFunctionDef = _stmt_FunctionDef

    def _stmt_ClassDef(self, scope, node):
        for expression in node.decorator_list + node.bases + [k.value for k in node.keywords]:
            self._expression(scope, expression)
        self._bind(scope, node.name, node.lineno, "class", node)
        child = self._new_scope(CLASS, node, scope)
        self._statements(child, node.body)

    def _stmt_Assign(self, scope, node):
        self._expression(scope, node.value)
        for target in node.targets:
            self._bind_target(scope, target, "assign", node.value, node)

    def _stmt_AnnAssign(self, scope, node):
        self._expression(scope, node.value)
        self._expression(scope, node.annotation)
        if isinstance(node.target, ast.Name):
            self._bind(scope, node.target.id, node.target.lineno, "assign", node, node.value,
                       target=node.target, annotation=node.annotation)
        else:
            self._expression(scope, node.target)

    def _stmt_AugAssign(self, scope, node):
        self._expression(scope, node.value)
        target = node.target
        if isinstance(target, ast.Name):
            if target.id not in scope.bindings:
                self._bind(scope, target.id, target.lineno, "augassign", node, target=target)
        else:
            self._expression(scope, target)

    def _stmt_For(self, scope, node):
        self._expression(scope, node.iter)
        self._bind_target(scope, node.target, "loop", None, node)
        self._statements(scope, node.body)
        self._statements(scope, node.orelse)

    _stmt_AsyncFor = _stmt_For

    def _stmt_With(self, scope, node):
        for item in node.items:
            self._expression(scope, item.context_expr)
            if item.optional_vars is not None:
                self._bind_target(scope, item.optional_vars, "with", None, node,
                                  context=item.context_expr)
        self._statements(scope, node.body)

    _stmt_AsyncWith = _stmt_With

    def _stmt_Try(self, scope, node):
        self._statements(scope, node.body)
        for handler in node.handlers:
            self._expression(scope, handler.type)
            if handler.name:
                self._bind(scope, handler.name, handler.lineno, "except", handler,
                           exception=handler.type)
            self._statements(scope, handler.body)
        self._statements(scope, node.orelse)
        self._statements(scope, node.finalbody)

    _stmt_TryStar = _stmt_Try

    def _stmt_Match(self, scope, node):
        self._expression(scope, node.subject)
        for case in node.cases:
            for pattern in ast.walk(case.pattern):
                for attribute in ("name", "rest"):
                    name = getattr(pattern, attribute, None)
                    if isinstance(name, str):
                        self._bind(scope, name, pattern.lineno, "pattern", case, target=pattern)
                if isinstance(pattern, ast.MatchValue):
                    self._expression(scope, pattern.value)
            self._expression(scope, case.guard)
            self._statements(scope, case.body)

    def _stmt_Import(self, scope, node):
        for alias in node.names:
            if alias.asname:
                self._bind(scope, alias.asname, node.lineno, "import", node, target=alias,
                           module=alias.name)
            else:
                top = alias.name.split(".")[0]
                self._bind(scope, top, node.lineno, "import", node, target=alias, module=top)

    def _stmt_ImportFrom(self, scope, node):
        for alias in node.names:
            if alias.name == "*":
                scope.star_imports.append(
                    StarImport(node.module or "", node.level, node.lineno, scope, node))
            else:
                self._bind(scope, alias.asname or alias.name, node.lineno, "importfrom", node,
                           target=alias, module=node.module or "", level=node.level,
                           attribute=alias.name)

    def _stmt_Global(self, scope, node):
        pass

    _stmt_Nonlocal = _stmt_Global

    # -- expressions -------------------------------------------------------

    def _expression(self, scope, node):
        if node is None or not isinstance(node, ast.AST):
            return
        if isinstance(node, ast.Lambda):
            for default in node.args.defaults + node.args.kw_defaults:
                self._expression(scope, default)
            child = self._new_scope(LAMBDA, node, scope)
            self._bind_arguments(child, node)
            self._expression(child, node.body)
        elif isinstance(node, _COMPREHENSION_NODES):
            child = self._new_scope(COMPREHENSION, node, scope)
            for index, generator in enumerate(node.generators):
                self._expression(scope if index == 0 else child, generator.iter)
                self._bind_target(child, generator.target, "comprehension", None, generator)
                for condition in generator.ifs:
                    self._expression(child, condition)
            if isinstance(node, ast.DictComp):
                self._expression(child, node.key)
                self._expression(child, node.value)
            else:
                self._expression(child, node.elt)
        elif isinstance(node, ast.NamedExpr):
            self._expression(scope, node.value)
            target_scope = scope
            while target_scope.kind == COMPREHENSION:
                target_scope = target_scope.parent
            self._bind(target_scope, node.target.id, node.target.lineno, "assign", node, node.value,
                       target=node.target)
        else:
            for child in ast.iter_child_nodes(node):
                self._expression(scope, child)
