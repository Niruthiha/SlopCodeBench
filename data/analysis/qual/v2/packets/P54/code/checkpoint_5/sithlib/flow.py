"""Flow analysis.

Secret: how control flow inside one scope is approximated — which bindings
of a name can reach a statement (branches merge, ``return``/``raise``/
``break``/``continue`` end a path, loops run zero or one time, handlers see
any prefix of their ``try`` body) and which narrowing conditions
(``isinstance`` checks, ``is None`` tests, asserts) hold there.

A state maps a name to a set of facts ``(binding, constraints)``. The binding
``OUTER`` stands for "whatever the enclosing scope provides"; it only appears
when a name that is not bound locally gets narrowed.
"""

import ast

from . import scopes

OUTER = None


class Constraint:
    """A condition known to hold for a name: ``isinstance`` or ``is None``."""

    ISINSTANCE, NONE = "isinstance", "none"

    def __init__(self, kind, positive, expr=None):
        self.kind = kind
        self.positive = positive
        self.expr = expr

    def negated(self):
        return Constraint(self.kind, not self.positive, self.expr)


class State:
    def __init__(self, names=None, dead=False):
        self.names = names if names is not None else {}
        self.dead = dead

    def facts(self, name):
        return self.names.get(name)

    def bound(self, binding):
        names = dict(self.names)
        names[binding.name] = frozenset([(binding, ())])
        return State(names, self.dead)

    def narrowed(self, conditions):
        if not conditions:
            return self
        names = dict(self.names)
        for name, constraint in conditions:
            facts = names.get(name) or frozenset([(OUTER, ())])
            names[name] = frozenset((b, c + (constraint,)) for b, c in facts)
        return State(names, self.dead)

    def killed(self):
        return State(self.names, True)


def merge(states, keep_dead=False):
    """Join the states of paths meeting at one point."""
    states = [s for s in states if s is not None]
    live = [s for s in states if not s.dead]
    pool = states if keep_dead or not live else live
    if not pool:
        return State(dead=True)
    if len(pool) == 1:
        return State(pool[0].names, not live and not keep_dead)
    names = {}
    for state in pool:
        for name in state.names:
            names.setdefault(name, None)
    for name in names:
        facts = set()
        missing = False
        for state in pool:
            found = state.names.get(name)
            if found is None:
                missing = True
            else:
                facts.update(found)
        if missing and any(b is OUTER for b, _ in facts):
            facts.add((OUTER, ()))
        names[name] = frozenset(facts)
    return State(names, not live and not keep_dead)


class _Loop:
    def __init__(self):
        self.breaks = []
        self.continues = []


class Flow:
    """Reaching bindings at every statement of one scope."""

    def __init__(self, scope):
        self.scope = scope
        self.before = {}
        self.after = {}
        self._exits = []
        self._by_stmt = {}
        stray = []
        start = State()
        for event in scope.events:
            if not event.name or event.form == scopes.STAR:
                continue
            if event.form == scopes.PARAM:
                start = start.bound(event)
            elif event.home is scope and event.stmt is not None:
                self._by_stmt.setdefault(id(event.stmt), []).append(event)
            else:
                stray.append(event)
        body = scope.node.body if scope.node is not None else []
        last = self._block(body, start, None)
        end = merge([last] + self._exits, keep_dead=True)
        for event in stray:
            facts = set(end.names.get(event.name, ()))
            facts.add((event, ()))
            end.names[event.name] = frozenset(facts)
        self.end = end
        self.body = body

    # -- statements ------------------------------------------------------
    def _apply(self, node, state):
        for event in self._by_stmt.get(id(node), ()):
            state = state.bound(event)
        return state

    def _block(self, statements, state, loop):
        for statement in statements:
            self.before[id(statement)] = state
            state = self._statement(statement, state, loop)
            self.after[id(statement)] = state
        return state

    def _statement(self, node, state, loop):
        if isinstance(node, ast.If):
            state = self._apply(node, state)
            positive, negative = conditions(node.test)
            body = self._block(node.body, state.narrowed(positive), loop)
            other = self._block(node.orelse, state.narrowed(negative), loop)
            merged = merge([body, other])
            if not body.dead and not other.dead:
                merged = _forget(merged, positive, negative)
            return merged
        if isinstance(node, ast.While):
            state = self._apply(node, state)
            positive, negative = conditions(node.test)
            inner = _Loop()
            body = self._block(node.body, state.narrowed(positive), inner)
            if _always_true(node.test):
                normal = State(state.names, True)
            else:
                normal = merge([state, body] + inner.continues).narrowed(negative)
            other = self._block(node.orelse, normal, loop)
            return merge([other] + inner.breaks)
        if isinstance(node, (ast.For, ast.AsyncFor)):
            inner = _Loop()
            body = self._block(node.body, self._apply(node, state), inner)
            normal = merge([state, body] + inner.continues)
            other = self._block(node.orelse, normal, loop)
            return merge([other] + inner.breaks)
        if isinstance(node, (ast.With, ast.AsyncWith)):
            return self._block(node.body, self._apply(node, state), loop)
        if isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            return self._try(node, state, loop)
        if isinstance(node, ast.Match):
            state = self._apply(node, state)
            ends = []
            exhaustive = False
            for case in node.cases:
                start = self._apply(case, state)
                self.before[id(case)] = start
                ends.append(self._block(case.body, start, loop))
                if case.guard is None and isinstance(case.pattern, ast.MatchAs) \
                        and case.pattern.pattern is None:
                    exhaustive = True
            if not exhaustive:
                ends.append(state)
            return merge(ends)
        if isinstance(node, (ast.Return, ast.Raise)):
            state = self._apply(node, state)
            self._exits.append(state)
            return state.killed()
        if isinstance(node, ast.Break):
            if loop is not None:
                loop.breaks.append(state)
            return state.killed()
        if isinstance(node, ast.Continue):
            if loop is not None:
                loop.continues.append(state)
            return state.killed()
        if isinstance(node, ast.Assert):
            state = self._apply(node, state)
            return state.narrowed(conditions(node.test)[0])
        return self._apply(node, state)

    def _try(self, node, state, loop):
        body = self._block(node.body, state, loop)
        partial = [state] + [self.after[id(s)] for s in node.body if id(s) in self.after]
        handler_start = merge(partial, keep_dead=True)
        ends = []
        for handler in node.handlers:
            start = self._apply(handler, handler_start)
            self.before[id(handler)] = start
            ends.append(self._block(handler.body, start, loop))
        ends.insert(0, self._block(node.orelse, body, loop))
        joined = merge(ends)
        if node.finalbody:
            start = merge(ends + [handler_start], keep_dead=True) if joined.dead else joined
            final = self._block(node.finalbody, start, loop)
            return State(final.names, joined.dead or final.dead)
        return joined

    # -- queries ---------------------------------------------------------
    def state_before(self, node):
        """State just before ``node`` (a statement, handler or case) runs."""
        return self.before.get(id(node))

    def state_at(self, line, col, indent):
        """State at a cursor that may sit between or after statements.

        ``indent`` is the indentation of the cursor's line (used to decide
        which block an empty or broken line belongs to).
        """
        return self._find(self.body, line, col, indent, self.end)

    def _find(self, statements, line, col, indent, fallback):
        previous = None
        for statement in statements:
            if (statement.lineno, statement.col_offset) > (line, col):
                break
            previous = statement
        if previous is None:
            return self.before.get(id(statements[0]), fallback) if statements else fallback
        blocks = _blocks(previous)
        if line <= (previous.end_lineno or previous.lineno):
            inner = [block for block in blocks
                     if (block[0].lineno, block[0].col_offset) <= (line, col)
                     or block[0].lineno < line]
            if inner:
                block = inner[-1]
                return self._find(block, line, col, indent,
                                  self.after.get(id(block[-1]), fallback))
            return self.before.get(id(previous), fallback)
        if blocks and indent > previous.col_offset:
            block = blocks[-1]
            return self._find(block, line, col, indent, self.after.get(id(block[-1]), fallback))
        return self.after.get(id(previous), fallback)


def _forget(state, positive, negative):
    """Drop narrowing by one test where both of its outcomes rejoin.

    A binding narrowed one way on the true path and the other way on the
    false path is, after the paths meet, just the binding again. (When one
    path rebinds the name, the other path's narrowing is kept.)
    """
    own = {id(c) for _, c in positive + negative}
    if not own:
        return state
    names = dict(state.names)
    for name, facts in state.names.items():
        groups = {}
        for binding, constraints in facts:
            base = tuple(c for c in constraints if id(c) not in own)
            groups.setdefault((binding, base), []).append(constraints)
        if all(len(variants) == 1 for variants in groups.values()):
            continue
        result = set()
        for (binding, base), variants in groups.items():
            if len(variants) > 1:
                result.add((binding, base))
            else:
                result.add((binding, variants[0]))
        names[name] = frozenset(result)
    return State(names, state.dead)


def _blocks(node):
    """Nested non-empty statement lists of a compound statement, in source order."""
    found = []
    for field in ("body", "handlers", "orelse", "finalbody", "cases"):
        value = getattr(node, field, None)
        if not value or not isinstance(value, list):
            continue
        if field in ("handlers", "cases"):
            found.extend(item.body for item in value if item.body)
        else:
            found.append(value)
    found.sort(key=lambda block: (block[0].lineno, block[0].col_offset))
    return found


def _always_true(test):
    return isinstance(test, ast.Constant) and bool(test.value)


def conditions(test):
    """``(holds_if_true, holds_if_false)``: lists of (name, Constraint)."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        positive, negative = conditions(test.operand)
        return negative, positive
    if isinstance(test, ast.BoolOp):
        parts = [conditions(value) for value in test.values]
        if isinstance(test.op, ast.And):
            return [c for p, _ in parts for c in p], []
        return [], [c for _, n in parts for c in n]
    if isinstance(test, ast.NamedExpr):
        return conditions(test.value)
    if isinstance(test, ast.Call) and isinstance(test.func, ast.Name) \
            and test.func.id == "isinstance" and len(test.args) == 2 \
            and isinstance(test.args[0], ast.Name):
        constraint = Constraint(Constraint.ISINSTANCE, True, test.args[1])
        name = test.args[0].id
        return [(name, constraint)], [(name, constraint.negated())]
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        left, right = test.left, test.comparators[0]
        if _is_none(left):
            left, right = right, left
        if isinstance(left, ast.Name) and _is_none(right):
            op = test.ops[0]
            if isinstance(op, (ast.Is, ast.Eq)):
                positive = True
            elif isinstance(op, (ast.IsNot, ast.NotEq)):
                positive = False
            else:
                return [], []
            constraint = Constraint(Constraint.NONE, positive)
            return [(left.id, constraint)], [(left.id, constraint.negated())]
    return [], []


def _is_none(node):
    return isinstance(node, ast.Constant) and node.value is None
