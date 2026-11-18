"""Static type inference: names, bindings and expressions to (unions of) values."""
import ast
import itertools
import types
import typing

from .builtin_scope import builtin_entries
from .entries import BindingEntry
from .flow import Fact, FlowAnalyzer, initial_facts, merge
from .members import MemberResolver
from .scopes import CLASS, FUNCTION, LAMBDA, MODULE, Binding, walk_local
from .values import (
    LocalClass,
    LocalFunction,
    LocalInstance,
    RuntimeClass,
    RuntimeInstance,
    unique,
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

_NUMERIC_TOWER = (bool, int, float, complex)

_OPERATOR_METHODS = {
    ast.Add: "__add__", ast.Sub: "__sub__", ast.Mult: "__mul__", ast.MatMult: "__matmul__",
    ast.Div: "__truediv__", ast.FloorDiv: "__floordiv__", ast.Mod: "__mod__",
    ast.Pow: "__pow__", ast.LShift: "__lshift__", ast.RShift: "__rshift__",
    ast.BitOr: "__or__", ast.BitXor: "__xor__", ast.BitAnd: "__and__",
}

NONE = RuntimeInstance(type(None))

_TYPING_FORM_NAMES = ("Optional", "Union", "ClassVar", "Final", "Annotated", "Type",
                      "Required", "NotRequired")
_TYPING_FORMS = {id(getattr(typing, name)): name
                 for name in _TYPING_FORM_NAMES if hasattr(typing, name)}


def instance_of(value, init_args=None):
    """The instance value produced by calling a class value."""
    if isinstance(value, LocalClass):
        return LocalInstance(value, init_args)
    if isinstance(value, RuntimeClass):
        return RuntimeInstance(value.obj)
    return None


def is_none(value):
    return isinstance(value, RuntimeInstance) and value.cls is type(None)


class BuiltinBinding:
    """Stands in for a binding when a name resolves to the builtins module."""

    kind = "builtin"

    def __init__(self, name, entry):
        self.name = name
        self.entry = entry

    def value(self):
        return self.entry.value()


class _Frame:
    """Argument values for one call of a local function."""

    _ids = itertools.count()

    def __init__(self, scope, args, bound):
        self.id = next(self._ids)
        self.scope = scope
        self.args = args
        self.bound = bound


class Inferrer:
    def __init__(self, importer):
        self.importer = importer
        self.members = MemberResolver(self)
        self._builtins = builtin_entries()
        self._builtin_bindings = {}
        self._binding_cache = {}
        self._entries_cache = {}
        self._flow_cache = {}
        self._synthetic = {}
        self._star_names = {}
        self._active = set()
        self._frames = []
        self._depth = 0

    # -- scopes and name listing (completion) -------------------------------

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

    def visible_entries(self, scope, line):
        """All names visible at `line` in `scope`, innermost definitions first."""
        result = {}
        for current, limit in self.scope_chain(scope, line, strict=True):
            for name, entry in self.scope_entries(current, limit).items():
                result.setdefault(name, entry)
        for name, entry in self._builtins.items():
            result.setdefault(name, entry)
        return result

    # -- flow-sensitive name resolution ------------------------------------------

    def resolution_chain(self, scope, pos, strict):
        """(scope, target position) pairs for resolving a name used at `pos` in `scope`.

        Code in an enclosing scope is seen as it stands at the end of that
        scope once a function boundary is crossed (late binding), except in
        strict mode, which only sees what precedes the cursor.
        """
        chain = []
        target = pos
        for index, current in enumerate(scope.chain()):
            if current.kind == CLASS and index > 0:
                continue
            chain.append((current, target))
            if current.kind in (FUNCTION, LAMBDA) and not strict:
                target = None
        return chain

    def binds(self, scope, name):
        if name in scope.bindings:
            return True
        return any(self._star_binding(star, name) is not None for star in scope.star_imports)

    def _star_binding(self, star, name):
        """A synthetic binding for `name` if the star import `star` provides it."""
        key = ("star", id(star), name)
        if key not in self._synthetic:
            if id(star) not in self._star_names:
                module = self.importer.import_module(star.scope.module, star.module, star.level)
                self._star_names[id(star)] = (
                    set(self.members.public(module)) if module is not None else set())
            binding = None
            if name in self._star_names[id(star)]:
                binding = Binding(name, star.line, "importfrom", star.node, star.scope,
                                  extra=dict(module=star.module, level=star.level, attribute=name))
            self._synthetic[key] = binding
        return self._synthetic[key]

    def synthetic_binding(self, scope):
        """Factory for bindings that scope analysis does not record (see FlowAnalyzer)."""
        stars = {id(star.node): star for star in scope.star_imports}

        def create(kind, node, name):
            if kind == "star":
                star = stars.get(id(node))
                return self._star_binding(star, name) if star is not None else None
            key = (kind, id(node), name)
            if key not in self._synthetic:
                self._synthetic[key] = Binding(name, node.lineno, "augassign", node, scope,
                                               target=node.target)
            return self._synthetic[key]

        return create

    def flow_facts(self, scope, name, target):
        key = (id(scope), name, target)
        if key not in self._flow_cache:
            analyzer = FlowAnalyzer(scope, name, target, self.synthetic_binding(scope))
            self._flow_cache[key] = analyzer.run(initial_facts(scope, name))
        return self._flow_cache[key]

    def name_facts(self, name, scope, pos, strict=False):
        """Facts (bindings plus narrowings) for `name` used at `pos` in `scope`."""
        chain = self.resolution_chain(scope, pos, strict)
        return merge(self._facts_from(name, chain, 0, ()))

    def _facts_from(self, name, chain, index, narrowings):
        for position in range(index, len(chain)):
            current, target = chain[position]
            if not self.binds(current, name):
                if target is None or current.kind not in (FUNCTION, CLASS, MODULE):
                    continue
                # The name comes from further out, but conditions here may narrow it.
                facts = self.flow_facts(current, name, target) or [Fact(None)]
                result = []
                for fact in facts:
                    result += self._facts_from(name, chain, position + 1,
                                               fact.narrowings + narrowings)
                return result
            result = []
            for fact in self.flow_facts(current, name, target):
                combined = fact.narrowings + narrowings
                if fact.binding is None:
                    result += self._facts_from(name, chain, position + 1, combined)
                    continue
                prior = []
                for previous in fact.prior:
                    if previous.binding is None:
                        prior += self._facts_from(name, chain, position + 1, previous.narrowings)
                    else:
                        prior.append(previous)
                result.append(Fact(fact.binding, combined, prior))
            return result
        entry = self._builtins.get(name)
        if entry is None:
            return []
        if name not in self._builtin_bindings:
            self._builtin_bindings[name] = BuiltinBinding(name, entry)
        return [Fact(self._builtin_bindings[name], narrowings)]

    def scope_facts(self, scope, name):
        """Facts for `name` at the end of `scope` (bindings made in `scope` only)."""
        return [f for f in self.flow_facts(scope, name, None) if f.binding is not None]

    def scope_values(self, scope, name):
        return unique(v for f in self.scope_facts(scope, name) for v in self.fact_values(f))

    def name_values(self, name, scope, pos, strict=False):
        values = []
        for fact in self.name_facts(name, scope, pos, strict):
            values += self.fact_values(fact)
        return unique(values)

    def fact_values(self, fact):
        binding = fact.binding
        if binding is None:
            return []
        if isinstance(binding, BuiltinBinding):
            values = [binding.value()]
        elif binding.kind == "augassign":
            if fact.prior:
                node = binding.node
                lefts = unique(v for p in fact.prior for v in self.fact_values(p))
                values = self._operator_values(node.op, lefts, node.value, binding.scope, None, False)
                values = values or lefts
            else:
                values = self.infer_values(binding.node.value, binding.scope)
        else:
            values = self.binding_values(binding)
        values = unique(values)
        for narrowing in fact.narrowings:
            values = self.narrow(narrowing, values)
        return values

    # -- narrowing ---------------------------------------------------------------

    def narrow(self, narrowing, values):
        if narrowing.kind == "none":
            if narrowing.positive:
                return [v for v in values if is_none(v)] or [NONE]
            return [v for v in values if not is_none(v)]
        if narrowing.kind == "truthy":
            return [v for v in values if not is_none(v)]
        if narrowing.kind == "isinstance":
            classes = self.classinfo(narrowing.node, narrowing.scope)
            if not classes:
                return values
            if not narrowing.positive:
                return [v for v in values if not self.is_instance(v, classes)]
            result = []
            for value in values:
                if self.is_instance(value, classes):
                    result.append(value)
                    continue
                cls = self.class_of(value)
                if cls is not None:
                    result += [instance_of(c) for c in classes if self.is_subclass(c, cls)]
            return unique(result) or unique(instance_of(c) for c in classes)
        return values

    def classinfo(self, node, scope):
        elements = node.elts if isinstance(node, ast.Tuple) else [node]
        classes = []
        for element in elements:
            classes += [v for v in self.infer_values(element, scope)
                        if isinstance(v, (LocalClass, RuntimeClass))]
        return unique(classes)

    @staticmethod
    def class_of(value):
        if isinstance(value, LocalInstance):
            return value.cls
        if isinstance(value, RuntimeInstance):
            return RuntimeClass(value.cls)
        return None

    def is_instance(self, value, classes):
        cls = self.class_of(value)
        return cls is not None and any(self.is_subclass(cls, c) for c in classes)

    def is_subclass(self, cls, parent):
        if isinstance(parent, RuntimeClass) and parent.obj is object:
            return True
        if isinstance(cls, RuntimeClass):
            if not isinstance(parent, RuntimeClass):
                return False
            try:
                return issubclass(cls.obj, parent.obj)
            except TypeError:
                return False
        for current in self.members.mro(cls):
            if isinstance(parent, LocalClass) and current.scope is parent.scope:
                return True
            if isinstance(parent, RuntimeClass):
                for base in self.members.runtime_bases(current):
                    if self.is_subclass(base, parent):
                        return True
        return False

    # -- bindings ------------------------------------------------------------

    def _frame_signature(self):
        return tuple(frame.id for frame in self._frames)

    def infer_binding(self, binding):
        values = self.binding_values(binding)
        return values[0] if values else None

    def binding_values(self, binding):
        key = (id(binding), self._frame_signature())
        if key in self._binding_cache:
            return self._binding_cache[key]
        if key in self._active:
            return []
        self._active.add(key)
        try:
            values = unique(self._binding_values(binding))
        except RecursionError:
            values = []
        finally:
            self._active.discard(key)
        self._binding_cache[key] = values
        return values

    def _binding_values(self, binding):
        context = binding.scope.module
        kind = binding.kind
        extra = binding.extra
        if kind == "def":
            scope = context.scope_of(binding.node)
            return [LocalFunction(scope)] if scope else []
        if kind == "class":
            scope = context.scope_of(binding.node)
            return [LocalClass(scope)] if scope else []
        if kind == "import":
            return [self.importer.import_absolute(extra["module"])]
        if kind == "importfrom":
            return self.resolve_from_values(context, extra["module"], extra["level"],
                                            extra["attribute"])
        if kind == "assign":
            annotation = extra.get("annotation")
            if annotation is not None:
                values = self.annotation_values(annotation, binding.scope)
                if values:
                    return values
            if binding.value is not None:
                return self.infer_values(binding.value, binding.scope)
            return []
        if kind == "augassign":
            return self.infer_values(binding.node.value, binding.scope)
        if kind == "param":
            return self._param_values(binding)
        if kind == "except":
            exception = extra.get("exception")
            if exception is None:
                return []
            return [instance_of(c) for c in self.classinfo(exception, binding.scope)]
        if kind == "loop":
            if isinstance(binding.node.target, ast.Name):
                return self.iteration_values(binding.node.iter, binding.scope)
            return []
        if kind == "comprehension":
            generator = binding.node
            if isinstance(generator.target, ast.Name):
                outer = binding.scope
                if binding.scope.node.generators[0] is generator:
                    outer = binding.scope.parent
                return self.iteration_values(generator.iter, outer)
            return []
        if kind == "with":
            for item in binding.node.items:
                if isinstance(item.optional_vars, ast.Name) and item.optional_vars.id == binding.name:
                    return self.enter_values(item.context_expr, binding.scope)
            return []
        if kind == "pattern":
            pattern = binding.target
            if isinstance(pattern, ast.MatchAs) and isinstance(pattern.pattern, ast.MatchClass):
                return [instance_of(c) for c in self.classinfo(pattern.pattern.cls, binding.scope)]
            return []
        return []

    def in_frame(self, scope, args, bound, function):
        """Call `function()` with the parameters of `scope` bound to `args`/`bound`."""
        self._frames.append(_Frame(scope, args, bound))
        try:
            return function()
        finally:
            self._frames.pop()

    def resolve_from_values(self, context, module, level, attribute):
        """The values imported by `from <module> import <attribute>`."""
        if level and not module:
            submodule = self.importer.import_relative(context, attribute, level)
            if submodule is not None:
                return [submodule]
        base = self.importer.import_module(context, module, level)
        if base is not None:
            values = self.members.member_values(base, attribute)
            if values:
                return values
        if not level and module:
            return [self.importer.import_absolute(f"{module}.{attribute}")]
        return []

    def resolve_from(self, context, module, level, attribute):
        values = unique(self.resolve_from_values(context, module, level, attribute))
        return values[0] if values else None

    def annotation_values(self, annotation, scope, pos=None):
        """Instances described by a type annotation."""
        if annotation is None:
            return []
        if isinstance(annotation, ast.Constant):
            if annotation.value is None:
                return [NONE]
            if isinstance(annotation.value, str):
                try:
                    parsed = ast.parse(annotation.value.strip(), mode="eval").body
                except SyntaxError:
                    return []
                return self.annotation_values(parsed, scope, pos or _position(annotation))
            return []
        if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
            return unique(self.annotation_values(annotation.left, scope, pos)
                          + self.annotation_values(annotation.right, scope, pos))
        if isinstance(annotation, ast.Subscript):
            arguments = annotation.slice
            arguments = arguments.elts if isinstance(arguments, ast.Tuple) else [arguments]
            special = _typing_form(annotation.value, self.infer_values(annotation.value, scope, pos))
            if special == "Optional":
                return unique(self.annotation_values(arguments[0], scope, pos) + [NONE])
            if special == "Union":
                return unique(v for a in arguments for v in self.annotation_values(a, scope, pos))
            if special in ("ClassVar", "Final", "Annotated", "Required", "NotRequired"):
                return self.annotation_values(arguments[0], scope, pos)
            if special == "Type":
                return [v for v in self.infer_values(arguments[0], scope, pos)
                        if isinstance(v, (LocalClass, RuntimeClass))]
            annotation = annotation.value
        values = self.infer_values(annotation, scope, pos)
        return unique(instance_of(v) for v in values if isinstance(v, (LocalClass, RuntimeClass)))

    def _frame_for(self, scope):
        for frame in reversed(self._frames):
            if frame.scope is scope:
                return frame
        return None

    def _param_values(self, binding):
        node = binding.node
        arg = binding.extra["arg"]
        outer = binding.scope.parent
        if arg.annotation is not None:
            values = self.annotation_values(arg.annotation, outer)
            if values:
                if arg is node.args.vararg:
                    return [RuntimeInstance(tuple)]
                if arg is node.args.kwarg:
                    return [RuntimeInstance(dict)]
                return values
        positional = node.args.posonlyargs + node.args.args
        frame = self._frame_for(binding.scope)
        if frame is not None:
            if arg.arg in frame.args:
                return frame.args[arg.arg]
            if frame.bound is not None and positional and positional[0] is arg:
                return [frame.bound]
        if arg is node.args.vararg:
            return [RuntimeInstance(tuple)]
        if arg is node.args.kwarg:
            return [RuntimeInstance(dict)]
        default = _default_for(node.args, arg)
        if default is not None:
            return self.infer_values(default, outer)
        is_method = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and outer.kind == CLASS
        if is_method and positional and positional[0] is arg:
            decorators = {_decorator_name(d) for d in node.decorator_list}
            if "staticmethod" in decorators:
                return []
            cls = LocalClass(outer)
            if "classmethod" in decorators or node.name in ("__new__", "__init_subclass__"):
                return [cls]
            return [LocalInstance(cls)]
        return []

    # -- expressions -----------------------------------------------------------

    def infer_values(self, node, scope, pos=None, strict=False):
        """All values expression `node` may evaluate to in `scope`.

        Names are resolved at their own position in the source, or at `pos`
        when given (for expressions parsed separately from the module).
        """
        if node is None or scope is None or self._depth > _MAX_DEPTH:
            return []
        self._depth += 1
        try:
            return unique(self._infer(node, scope, pos, strict))
        except RecursionError:
            return []
        finally:
            self._depth -= 1

    def _infer(self, node, scope, pos, strict):
        if isinstance(node, ast.Constant):
            return [RuntimeInstance(type(node.value))]
        literal = _LITERAL_TYPES.get(type(node))
        if literal is not None:
            return [RuntimeInstance(literal)]
        if isinstance(node, ast.Name):
            return self.name_values(node.id, scope, pos or _position(node), strict)
        if isinstance(node, ast.Attribute):
            values = []
            for base in self.infer_values(node.value, scope, pos, strict):
                values += self.members.member_values(base, node.attr)
            return values
        if isinstance(node, ast.Call):
            return self._call_values(node, scope, pos, strict)
        if isinstance(node, ast.Await):
            if isinstance(node.value, ast.Call):
                return self._call_values(node.value, scope, pos, strict, awaited=True)
            return []
        if isinstance(node, ast.Lambda):
            lambda_scope = scope.module.scope_of(node)
            return [LocalFunction(lambda_scope)] if lambda_scope else []
        if isinstance(node, ast.BinOp):
            return self._binop_values(node, scope, pos, strict)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return [RuntimeInstance(bool)]
            return self.infer_values(node.operand, scope, pos, strict)
        if isinstance(node, ast.IfExp):
            return (self.infer_values(node.body, scope, pos, strict)
                    + self.infer_values(node.orelse, scope, pos, strict))
        if isinstance(node, ast.BoolOp):
            return [v for value in node.values for v in self.infer_values(value, scope, pos, strict)]
        if isinstance(node, ast.NamedExpr):
            return self.infer_values(node.value, scope, pos, strict)
        if isinstance(node, ast.Subscript):
            values = self.infer_values(node.value, scope, pos, strict)
            return [v for v in values if isinstance(v, RuntimeInstance) and v.cls in (str, bytes)]
        return []

    def _call_values(self, node, scope, pos, strict, awaited=False):
        values = []
        for function in self.infer_values(node.func, scope, pos, strict):
            values += self.call_result(function, node, scope, pos, strict, awaited)
        return values

    def call_result(self, function, call, scope, pos=None, strict=False, awaited=False):
        """Values returned by calling `function` with the arguments of `call`."""
        if isinstance(function, LocalClass):
            init = self.members.find_method(function, "__init__")
            args = None
            if init is not None:
                args = self.map_arguments(init.node, call, scope, pos, strict, offset=1)
            return [LocalInstance(function, args)]
        if isinstance(function, RuntimeClass):
            if function.obj is type and len(call.args) == 1:
                return [c for v in self.infer_values(call.args[0], scope, pos, strict)
                        for c in [self.class_of(v)] if c is not None]
            return [RuntimeInstance(function.obj)]
        if isinstance(function, LocalInstance):
            method = self.members.find_method(function.cls, "__call__")
            if method is None:
                return []
            function = LocalFunction(method.scope, function)
        if not isinstance(function, LocalFunction):
            return []
        node = function.node
        offset = 1 if function.bound is not None else 0
        args = self.map_arguments(node, call, scope, pos, strict, offset)
        if isinstance(node, ast.AsyncFunctionDef) and not awaited:
            return [RuntimeInstance(types.CoroutineType)]
        return self.return_values(function, args)

    def map_arguments(self, function_node, call, scope, pos, strict, offset=0):
        """{parameter name: values} for the arguments `call` passes to a function."""
        arguments = function_node.args
        positional = arguments.posonlyargs + arguments.args
        mapping = {}
        if call is None:
            return mapping
        for index, argument in enumerate(call.args):
            if isinstance(argument, ast.Starred):
                break
            if index + offset < len(positional):
                name = positional[index + offset].arg
                mapping[name] = self.infer_values(argument, scope, pos, strict)
        for keyword in call.keywords:
            if keyword.arg is not None:
                mapping[keyword.arg] = self.infer_values(keyword.value, scope, pos, strict)
        return {name: values for name, values in mapping.items() if values}

    def return_values(self, function, args=None):
        """The values returned by calling a locally defined function."""
        scope = function.scope
        node = scope.node
        key = ("return", id(node))
        if key in self._active:
            return []
        self._active.add(key)
        frame = _Frame(scope, args or {}, function.bound)
        self._frames.append(frame)
        try:
            if isinstance(node, ast.Lambda):
                return self.infer_values(node.body, scope)
            if node.returns is not None:
                values = self.annotation_values(node.returns, scope.parent)
                if values:
                    return values
            returns = []
            for child in walk_local(node.body):
                if isinstance(child, (ast.Yield, ast.YieldFrom)):
                    if isinstance(node, ast.AsyncFunctionDef):
                        return [RuntimeInstance(types.AsyncGeneratorType)]
                    return [RuntimeInstance(types.GeneratorType)]
                if isinstance(child, ast.Return):
                    returns.append(child)
            if not returns:
                return [NONE]
            values = []
            for statement in returns:
                if statement.value is None:
                    values.append(NONE)
                else:
                    values += self.infer_values(statement.value, scope)
            return unique(values)
        finally:
            self._frames.pop()
            self._active.discard(key)

    def iteration_values(self, iterable, scope):
        """Values produced by iterating over expression `iterable`."""
        if isinstance(iterable, (ast.List, ast.Tuple, ast.Set)):
            return unique(v for element in iterable.elts if not isinstance(element, ast.Starred)
                          for v in self.infer_values(element, scope))
        if isinstance(iterable, ast.Dict):
            return unique(v for key in iterable.keys if key is not None
                          for v in self.infer_values(key, scope))
        if isinstance(iterable, ast.Name):
            literals = []
            for fact in self.name_facts(iterable.id, scope, _position(iterable)):
                binding = fact.binding
                if (getattr(binding, "kind", None) == "assign" and binding.value is not None
                        and isinstance(binding.value, (ast.List, ast.Tuple, ast.Set, ast.Dict))):
                    literals += self.iteration_values(binding.value, binding.scope)
            if literals:
                return unique(literals)
        values = []
        for value in self.infer_values(iterable, scope):
            if isinstance(value, RuntimeInstance):
                if value.cls is str:
                    values.append(value)
                elif value.cls in (bytes, bytearray, range):
                    values.append(RuntimeInstance(int))
            elif isinstance(value, LocalInstance):
                method = self.members.find_method(value.cls, "__iter__")
                if method is not None:
                    for iterator in self.return_values(LocalFunction(method.scope, value)):
                        nxt = None
                        if isinstance(iterator, LocalInstance):
                            nxt = self.members.find_method(iterator.cls, "__next__")
                        if nxt is not None:
                            values += self.return_values(LocalFunction(nxt.scope, iterator))
        return unique(values)

    def enter_values(self, context_expr, scope):
        """The value bound by `with <context_expr> as name`."""
        values = []
        for value in self.infer_values(context_expr, scope):
            if isinstance(value, LocalInstance):
                method = self.members.find_method(value.cls, "__enter__")
                if method is not None:
                    values += self.return_values(LocalFunction(method.scope, value))
                    continue
            values.append(value)
        return unique(values)

    def _binop_values(self, node, scope, pos, strict):
        lefts = self.infer_values(node.left, scope, pos, strict)
        return self._operator_values(node.op, lefts, node.right, scope, pos, strict)

    def _operator_values(self, op, lefts, right_node, scope, pos, strict):
        """Values of `<left> <op> <right_node>` for each of the values `lefts`."""
        rights = None
        values = []
        for left in lefts:
            if isinstance(left, LocalInstance):
                method = self.members.find_method(left.cls, _OPERATOR_METHODS.get(type(op), ""))
                if method is not None:
                    values += self.return_values(LocalFunction(method.scope, left))
                continue
            if not isinstance(left, RuntimeInstance):
                continue
            if isinstance(op, ast.Mod) and left.cls in (str, bytes):
                values.append(left)
                continue
            if rights is None:
                rights = self.infer_values(right_node, scope, pos, strict)
            for right in rights:
                if not isinstance(right, RuntimeInstance):
                    continue
                if right.cls is left.cls:
                    if left.cls is bool and not isinstance(op, (ast.BitAnd, ast.BitOr, ast.BitXor)):
                        values.append(RuntimeInstance(int))
                    elif left.cls is int and isinstance(op, ast.Div):
                        values.append(RuntimeInstance(float))
                    else:
                        values.append(left)
                elif left.cls in _NUMERIC_TOWER and right.cls in _NUMERIC_TOWER:
                    wider = max(left.cls, right.cls, key=_NUMERIC_TOWER.index)
                    values.append(RuntimeInstance(max(wider, int, key=_NUMERIC_TOWER.index)))
                elif isinstance(op, ast.Mult) and {left.cls, right.cls} & {int, bool}:
                    sequence = right.cls if left.cls in (int, bool) else left.cls
                    values.append(RuntimeInstance(sequence))
        return values


def _position(node):
    return (node.lineno, node.col_offset)


def _typing_form(node, values):
    """The name of a typing special form (Optional, Union, ...) used as `node`."""
    for value in values:
        obj = getattr(value, "obj", None)
        if obj is not None and id(obj) in _TYPING_FORMS:
            return _TYPING_FORMS[id(obj)]
        if isinstance(value, RuntimeClass) and value.obj is type:
            return "Type"
    name = node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", None)
    if not values and name in _TYPING_FORM_NAMES:
        return name
    return None


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

