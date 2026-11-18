"""Static type inference: names, bindings and expressions to values."""
import ast
import types

from .builtin_scope import builtin_entries
from .entries import BindingEntry
from .members import MemberResolver
from .scopes import CLASS, FUNCTION, MODULE, walk_local
from .values import (
    LocalClass,
    LocalFunction,
    LocalInstance,
    RuntimeClass,
    RuntimeInstance,
)

_MAX_DEPTH = 60

_LITERAL_TYPES = {
    ast.JoinedStr: str,
    ast.List: list,
    ast.ListComp: list,
    ast.Tuple: tuple,
    ast.Dict: dict,
    ast.DictComp: dict,
    ast.Set: set,
    ast.SetComp: set,
    ast.GeneratorExp: types.GeneratorType,
    ast.Compare: bool,
}

def instance_of(value):
    """The instance value produced by calling a class value."""
    if isinstance(value, LocalClass):
        return LocalInstance(value)
    if isinstance(value, RuntimeClass):
        return RuntimeInstance(value.obj)
    return None


class Inferrer:
    def __init__(self, importer):
        self.importer = importer
        self.members = MemberResolver(self)
        self._builtins = builtin_entries()
        self._binding_cache = {}
        self._entries_cache = {}
        self._active = set()
        self._depth = 0

    # -- scopes and name lookup --------------------------------------------

    def scope_chain(self, scope, line, strict):
        """(scope, line limit) pairs for name resolution starting at `scope`.

        The innermost function/class scope ("local") and the module scope only
        see bindings up to `line`.  In non-strict mode (inference inside code
        bodies) the module scope is late-bound once a function scope was seen.
        Class scopes are only visible from directly inside the class body.
        """
        chain = []
        local_seen = False
        for index, current in enumerate(scope.chain()):
            if current.kind == CLASS and index > 0:
                continue
            if current.kind == MODULE:
                limit = line if strict or not local_seen else None
            elif current.kind in (FUNCTION, CLASS) and not local_seen:
                limit = line
                local_seen = True
            else:
                limit = None
            chain.append((current, limit))
        return chain

    def scope_entries(self, scope, limit=None):
        """Entries for names bound in `scope` (at or before line `limit`)."""
        key = (id(scope), limit)
        if key in self._entries_cache:
            return self._entries_cache[key]
        self._entries_cache[key] = {}
        chosen = {}
        for name, bindings in scope.bindings.items():
            binding = _latest_binding(bindings, limit)
            if binding is not None:
                chosen[name] = (binding.line, BindingEntry(binding, self))
        for star in scope.star_imports:
            if limit is not None and star.line > limit:
                continue
            module = self.importer.import_module(scope.module, star.module, star.level)
            if module is None:
                continue
            for name, entry in self.members.public(module).items():
                if name not in chosen or chosen[name][0] < star.line:
                    chosen[name] = (star.line, entry)
        entries = {name: entry for name, (_, entry) in chosen.items()}
        self._entries_cache[key] = entries
        return entries

    def lookup(self, name, scope, line, strict=False):
        for current, limit in self.scope_chain(scope, line, strict):
            entry = self.scope_entries(current, limit).get(name)
            if entry is not None:
                return entry
        return self._builtins.get(name)

    def visible_entries(self, scope, line):
        """All names visible at `line` in `scope`, innermost definitions first."""
        result = {}
        for current, limit in self.scope_chain(scope, line, strict=True):
            for name, entry in self.scope_entries(current, limit).items():
                result.setdefault(name, entry)
        for name, entry in self._builtins.items():
            result.setdefault(name, entry)
        return result

    # -- bindings ------------------------------------------------------------

    def infer_binding(self, binding):
        key = id(binding)
        if key in self._binding_cache:
            return self._binding_cache[key]
        if key in self._active:
            return None
        self._active.add(key)
        try:
            value = self._infer_binding(binding)
        finally:
            self._active.discard(key)
        self._binding_cache[key] = value
        return value

    def _infer_binding(self, binding):
        context = binding.scope.module
        kind = binding.kind
        extra = binding.extra
        if kind == "def":
            scope = context.scope_of(binding.node)
            return LocalFunction(scope) if scope else None
        if kind == "class":
            scope = context.scope_of(binding.node)
            return LocalClass(scope) if scope else None
        if kind == "import":
            return self.importer.import_absolute(extra["module"])
        if kind == "importfrom":
            return self.resolve_from(context, extra["module"], extra["level"], extra["attribute"])
        if kind == "assign":
            value = None
            if binding.value is not None:
                value = self.infer(binding.value, binding.scope, binding.line)
            if value is None and extra.get("annotation") is not None:
                value = self.infer_annotation(extra["annotation"], binding.scope, binding.line)
            return value
        if kind == "param":
            return self._infer_param(binding)
        if kind == "except":
            exception = extra.get("exception")
            if isinstance(exception, ast.Tuple) and exception.elts:
                exception = exception.elts[0]
            if exception is None:
                return None
            return instance_of(self.infer(exception, binding.scope, binding.line))
        return None

    def resolve_from(self, context, module, level, attribute):
        """The value imported by `from <module> import <attribute>`."""
        if level and not module:
            submodule = self.importer.import_relative(context, attribute, level)
            if submodule is not None:
                return submodule
        base = self.importer.import_module(context, module, level)
        if base is not None:
            value = self.members.member(base, attribute)
            if value is not None:
                return value
        if not level and module:
            return self.importer.import_absolute(f"{module}.{attribute}")
        return None

    def infer_annotation(self, annotation, scope, line):
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            try:
                annotation = ast.parse(annotation.value, mode="eval").body
            except SyntaxError:
                return None
        return instance_of(self.infer(annotation, scope, line))

    def _infer_param(self, binding):
        node = binding.node
        arg = binding.extra["arg"]
        outer = binding.scope.parent
        if arg.annotation is not None:
            value = self.infer_annotation(arg.annotation, outer, node.lineno)
            if value is not None:
                return value
        default = _default_for(node.args, arg)
        if default is not None:
            return self.infer(default, outer, node.lineno)
        positional = node.args.posonlyargs + node.args.args
        is_method = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and outer.kind == CLASS
        if is_method and positional and positional[0] is arg:
            decorators = {_decorator_name(d) for d in node.decorator_list}
            if "staticmethod" in decorators:
                return None
            cls = LocalClass(outer)
            if "classmethod" in decorators or node.name in ("__new__", "__init_subclass__"):
                return cls
            return LocalInstance(cls)
        return None

    # -- expressions -----------------------------------------------------------

    def infer(self, node, scope, line, strict=False):
        """Infer the value of expression `node` evaluated in `scope` at `line`."""
        if node is None or self._depth > _MAX_DEPTH:
            return None
        self._depth += 1
        try:
            return self._infer(node, scope, line, strict)
        except RecursionError:
            return None
        finally:
            self._depth -= 1

    def _infer(self, node, scope, line, strict):
        if isinstance(node, ast.Constant):
            return RuntimeInstance(type(node.value))
        literal = _LITERAL_TYPES.get(type(node))
        if literal is not None:
            return RuntimeInstance(literal)
        if isinstance(node, ast.Name):
            entry = self.lookup(node.id, scope, line, strict)
            return entry.value() if entry is not None else None
        if isinstance(node, ast.Attribute):
            base = self.infer(node.value, scope, line, strict)
            return self.members.member(base, node.attr) if base is not None else None
        if isinstance(node, ast.Call):
            return self._infer_call(node, scope, line, strict)
        if isinstance(node, ast.Lambda):
            lambda_scope = scope.module.scope_of(node)
            return LocalFunction(lambda_scope) if lambda_scope else None
        if isinstance(node, ast.BinOp):
            return self._infer_binop(node, scope, line, strict)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return RuntimeInstance(bool)
            return self.infer(node.operand, scope, line, strict)
        if isinstance(node, ast.IfExp):
            return self.infer(node.body, scope, line, strict) or self.infer(
                node.orelse, scope, line, strict)
        if isinstance(node, ast.NamedExpr):
            return self.infer(node.value, scope, line, strict)
        return None

    def _infer_call(self, node, scope, line, strict):
        function = self.infer(node.func, scope, line, strict)
        if function is None:
            return None
        if isinstance(function, (LocalClass, RuntimeClass)):
            return instance_of(function)
        if isinstance(function, LocalFunction):
            return self.infer_return(function)
        return None

    def _infer_binop(self, node, scope, line, strict):
        left = self.infer(node.left, scope, line, strict)
        if not isinstance(left, RuntimeInstance):
            return None
        if isinstance(node.op, ast.Mod) and left.cls in (str, bytes):
            return left
        right = self.infer(node.right, scope, line, strict)
        if isinstance(right, RuntimeInstance) and right.cls is left.cls:
            return left
        return None

    def infer_return(self, function):
        """The value returned by calling a locally defined function."""
        scope = function.scope
        node = scope.node
        key = ("return", id(node))
        if key in self._active:
            return None
        self._active.add(key)
        try:
            if isinstance(node, ast.Lambda):
                return self.infer(node.body, scope, node.lineno)
            if isinstance(node, ast.AsyncFunctionDef):
                return None
            returns = []
            for child in walk_local(node.body):
                if isinstance(child, (ast.Yield, ast.YieldFrom)):
                    return RuntimeInstance(types.GeneratorType)
                if isinstance(child, ast.Return) and child.value is not None:
                    returns.append(child)
            for statement in returns:
                value = self.infer(statement.value, scope, statement.lineno)
                if value is not None:
                    return value
            return None
        finally:
            self._active.discard(key)


def _latest_binding(bindings, limit):
    """The binding in effect at line `limit` (any line when `limit` is None).

    A binding on the limit line itself (e.g. `x = x + 1`, or the statement
    being typed) only counts when there is no earlier one.
    """
    if limit is None:
        pool = bindings
    else:
        pool = [b for b in bindings if b.line < limit] or [b for b in bindings if b.line == limit]
    if not pool:
        return None
    return max(enumerate(pool), key=lambda pair: (pair[1].line, pair[0]))[1]


def _default_for(arguments, arg):
    positional = arguments.posonlyargs + arguments.args
    if arg in positional:
        offset = len(positional) - len(arguments.defaults)
        index = positional.index(arg)
        return arguments.defaults[index - offset] if index >= offset else None
    if arg in arguments.kwonlyargs:
        return arguments.kw_defaults[arguments.kwonlyargs.index(arg)]
    return None


def _decorator_name(node):
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None

