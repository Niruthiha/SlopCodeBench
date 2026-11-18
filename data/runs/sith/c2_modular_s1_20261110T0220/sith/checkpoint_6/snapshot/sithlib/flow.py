"""Flow-sensitive name resolution within a single scope.

For one name in one scope, the analyzer walks the scope's statements in
execution order and tracks which bindings may be in effect, as a list of
facts.  Branches (`if`, loops, `try`, `match`) merge the facts of every path;
`return`, `raise`, `break` and `continue` end a path.  Conditions such as
`isinstance(x, A)` or `x is None` attach narrowings to the facts of the
branches they guard.  Values are only inferred later, from the facts.
"""
import ast

from .scopes import COMPREHENSION, FUNCTION, LAMBDA, walk_local

_COMPOUND = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Match)
if hasattr(ast, "TryStar"):
    _COMPOUND += (ast.TryStar,)
# Nodes whose children are not evaluated as part of the enclosing statement's header.
_NOT_HEADER = (ast.stmt, ast.Lambda, ast.excepthandler, ast.match_case)


class Narrowing:
    """A condition known to hold (`positive`) or not for a name at some point.

    Kinds: "isinstance" (`node` is the class expression, evaluated in
    `scope`), "none" (`x is None`) and "truthy" (`if x:`).
    """

    def __init__(self, kind, positive, node=None, scope=None):
        self.kind = kind
        self.positive = positive
        self.node = node
        self.scope = scope

    @property
    def key(self):
        return (self.kind, self.positive, id(self.node))


class Fact:
    """One way a name may be bound at a program point.

    `binding` is None when the name refers to an enclosing scope (or is not
    yet bound here).  `prior` holds the facts an augmented assignment updates.
    """

    def __init__(self, binding, narrowings=(), prior=()):
        self.binding = binding
        self.narrowings = tuple(narrowings)
        self.prior = tuple(prior)

    @property
    def key(self):
        return (id(self.binding), tuple(n.key for n in self.narrowings),
                tuple(p.key for p in self.prior))

    def narrowed(self, narrowing):
        return Fact(self.binding, self.narrowings + (narrowing,), self.prior)


def merge(*states):
    """The union of several lists of facts, without duplicates."""
    seen = set()
    result = []
    for state in states:
        for fact in state:
            if fact.key not in seen:
                seen.add(fact.key)
                result.append(fact)
    return result


def start_of(node):
    return (node.lineno, node.col_offset)


def end_of(node):
    return (node.end_lineno, node.end_col_offset)


class _Found(Exception):
    def __init__(self, state):
        super().__init__()
        self.state = state


class _Loop:
    def __init__(self):
        self.breaks = []
        self.continues = []


class FlowAnalyzer:
    """Computes the facts for `name` in `scope` at `target` ((line, byte col) or None for the end).

    `synthetic(kind, node, name)` creates bindings that scope analysis does
    not record: "star" for `from m import *` and "aug" for `x += ...`.
    """

    def __init__(self, scope, name, target, synthetic):
        self.scope = scope
        self.name = name
        self.target = target
        self.synthetic = synthetic
        self.searching = target is not None
        self.by_node = {}
        self.seen = set()
        self.loops = []
        for binding in scope.bindings.get(name, []):
            self.by_node.setdefault(id(binding.node), []).append(binding)
        self.has_walrus = any(isinstance(b.node, ast.NamedExpr) for b in scope.bindings.get(name, []))

    def run(self, initial):
        bindings = self.scope.bindings.get(self.name, [])
        if self.scope.kind in (LAMBDA, COMPREHENSION):
            return [Fact(b) for b in bindings] or list(initial)
        body = self.scope.node.body
        # Bindings made elsewhere, by functions declaring the name `global`.
        local = self.scope.local_node_ids
        if local is None:
            local = self.scope.local_node_ids = {id(node) for node in walk_local(body)}
        foreign = [Fact(b) for b in bindings if b.kind != "param" and id(b.node) not in local]
        try:
            state = self.block(body, list(initial))
        except _Found as found:
            state = found.state
            if not state or all(fact.binding is None for fact in state):
                return state
        return merge(state, foreign)

    # -- statements ----------------------------------------------------------

    def block(self, statements, state):
        for statement in statements:
            if self.searching:
                if self.target < start_of(statement):
                    raise _Found(state)
                if self.target <= end_of(statement):
                    self._enter(statement, state)
            state = self.statement(statement, state)
        return state

    def _enter(self, statement, state):
        """The target lies within `statement`: find the facts that reach it."""
        first = _first_child_start(statement)
        if first is None or self.target < first:
            raise _Found(state)
        raise _Found(self.statement(statement, state))

    def statement(self, node, state):
        handler = getattr(self, "_" + type(node).__name__, None)
        if handler is not None:
            return handler(node, state)
        return self._bind(node, self.walrus(node, state))

    def _bind(self, node, state):
        """The state after `node` binds the name (unchanged if it does not)."""
        bindings = self.by_node.get(id(node))
        if not bindings:
            return state
        for binding in bindings:
            self.seen.add(id(binding))
        return [Fact(bindings[-1])]

    def walrus(self, node, state):
        """Apply `(name := value)` bindings found in the header expressions of `node`."""
        if not self.has_walrus:
            return state
        stack = [c for c in ast.iter_child_nodes(node) if not isinstance(c, _NOT_HEADER)]
        if isinstance(node, ast.expr):
            stack = [node]
        while stack:
            child = stack.pop()
            if isinstance(child, ast.NamedExpr):
                state = self._bind(child, state)
            stack.extend(c for c in ast.iter_child_nodes(child) if not isinstance(c, _NOT_HEADER))
        return state

    def _ImportFrom(self, node, state):
        if any(alias.name == "*" for alias in node.names):
            binding = self.synthetic("star", node, self.name)
            return [Fact(binding)] if binding is not None else state
        return self._bind(node, state)

    def _AugAssign(self, node, state):
        state = self.walrus(node.value, state)
        if isinstance(node.target, ast.Name) and node.target.id == self.name:
            bindings = self.by_node.get(id(node))
            binding = bindings[-1] if bindings else self.synthetic("aug", node, self.name)
            self.seen.add(id(binding))
            return [Fact(binding, prior=state)]
        return state

    def _Delete(self, node, state):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == self.name:
                return []
        return state

    def _Return(self, node, state):
        self.walrus(node, state)
        return []

    _Raise = _Return

    def _Break(self, node, state):
        if self.loops:
            self.loops[-1].breaks.extend(state)
        return []

    def _Continue(self, node, state):
        if self.loops:
            self.loops[-1].continues.extend(state)
        return []

    def _Assert(self, node, state):
        return self.branch(node.test, self.walrus(node, state), True)

    def _If(self, node, state):
        state = self.walrus(node.test, state)
        body = self.block(node.body, self.branch(node.test, state, True))
        orelse = self.block(node.orelse, self.branch(node.test, state, False))
        return merge(body, orelse)

    def _loop(self, node, state, enter):
        """(state when the loop ends normally, states at `break`)."""
        searching = self.searching
        self.searching = False
        self.loops.append(_Loop())
        try:
            first = self.block(node.body, enter(state))
        finally:
            loop = self.loops.pop()
            self.searching = searching
        start = merge(state, first, loop.continues)
        self.loops.append(_Loop())
        try:
            end = self.block(node.body, enter(start))
        finally:
            loop = self.loops.pop()
        return merge(start, end, loop.continues), loop.breaks

    def _While(self, node, state):
        state = self.walrus(node.test, state)
        exit_state, breaks = self._loop(node, state, lambda s: self.branch(node.test, s, True))
        if isinstance(node.test, ast.Constant) and node.test.value:
            exit_state = []
        else:
            exit_state = self.branch(node.test, exit_state, False)
        return merge(self.block(node.orelse, exit_state), breaks)

    def _For(self, node, state):
        state = self.walrus(node.iter, state)
        bindings = self.by_node.get(id(node))
        if bindings:
            for binding in bindings:
                self.seen.add(id(binding))
            enter = lambda s: [Fact(bindings[-1])]
        else:
            enter = lambda s: s
        exit_state, breaks = self._loop(node, state, enter)
        return merge(self.block(node.orelse, exit_state), breaks)

    _AsyncFor = _For

    def _With(self, node, state):
        for item in node.items:
            state = self.walrus(item.context_expr, state)
        return self.block(node.body, self._bind(node, state))

    _AsyncWith = _With

    def _Try(self, node, state):
        body = self.block(node.body, state)
        handler_start = merge(state, body)
        ends = [self.block(node.orelse, body)]
        for handler in node.handlers:
            ends.append(self.block(handler.body, self._bind(handler, handler_start)))
        result = merge(*ends)
        if not node.finalbody:
            return result
        after = self.block(node.finalbody, merge(result, handler_start))
        return after if result else []

    _TryStar = _Try

    def _Match(self, node, state):
        state = self.walrus(node.subject, state)
        ends = [state]
        for case in node.cases:
            ends.append(self.block(case.body, self._bind(case, state)))
        return merge(*ends)

    # -- conditions ------------------------------------------------------------

    def branch(self, test, state, positive):
        """The facts in the branch where `test` is true (`positive`) or false."""
        if not state:
            return state
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return self.branch(test.operand, state, not positive)
        if isinstance(test, ast.BoolOp):
            if isinstance(test.op, ast.And) == positive:
                for value in test.values:
                    state = self.branch(value, state, positive)
                return state
            result = []
            for value in test.values:
                result = merge(result, self.branch(value, state, positive))
                state = self.branch(value, state, not positive)
            return result
        narrowing = self._narrowing(test, positive)
        if narrowing is None:
            return state
        return [fact.narrowed(narrowing) for fact in state]

    def _is_subject(self, node):
        if isinstance(node, ast.NamedExpr):
            node = node.target
        return isinstance(node, ast.Name) and node.id == self.name

    def _narrowing(self, test, positive):
        if self._is_subject(test):
            return Narrowing("truthy", True) if positive else None
        if isinstance(test, ast.Call) and isinstance(test.func, ast.Name) and len(test.args) == 2:
            if test.func.id == "isinstance" and self._is_subject(test.args[0]):
                return Narrowing("isinstance", positive, test.args[1], self.scope)
            return None
        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            left, op, right = test.left, test.ops[0], test.comparators[0]
            if _is_none(left) and self._is_subject(right):
                left, right = right, left
            if self._is_subject(left) and _is_none(right):
                if isinstance(op, (ast.Is, ast.Eq)):
                    return Narrowing("none", positive)
                if isinstance(op, (ast.IsNot, ast.NotEq)):
                    return Narrowing("none", not positive)
            if (positive and isinstance(op, (ast.Is, ast.Eq)) and isinstance(left, ast.Call)
                    and isinstance(left.func, ast.Name) and left.func.id == "type"
                    and len(left.args) == 1 and self._is_subject(left.args[0])):
                return Narrowing("isinstance", True, right, self.scope)
        return None


def _is_none(node):
    return isinstance(node, ast.Constant) and node.value is None


def _first_child_start(statement):
    """Start of the first nested statement (or case) of a compound statement."""
    if not isinstance(statement, _COMPOUND):
        return None
    if isinstance(statement, ast.Match):
        return start_of(statement.cases[0].pattern) if statement.cases else None
    return start_of(statement.body[0]) if statement.body else None


def initial_facts(scope, name):
    """Facts at the start of `scope`: its parameter binding, or the enclosing scope."""
    if scope.kind == FUNCTION:
        params = [b for b in scope.bindings.get(name, []) if b.kind == "param"]
        if params:
            return [Fact(params[-1])]
    return [Fact(None)]
