"""Multi-source pipelines: typing and execution of alias-scoped with blocks and joins.

Inside a join, every column reference is resolved to one side and renamed to
"L\\x1f<col>" or "R\\x1f<col>"; expressions are then evaluated against a
PairRow, which looks the name up in the left or right row.
"""
from datetime import timedelta

from . import badrecords as br
from . import dtypes
from .ast_nodes import Binary, ColumnRef, Projection
from .badrecords import BadRecord
from .errors import DSLSyntaxError, RuntimeFailure, TypeCheckError
from .evaluator import evaluate
from .parser import CURRENT_RELATION
from .pipeline import coerce, transform_rows
from .timeutil import format_utc
from .typecheck import check_declared, check_names, infer, walk

LEFT = "L"
RIGHT = "R"
_SEP = "\x1f"
EVENT_TIME = "timestamp"


class Relation:
    """Static view of a relation: the qualifiers naming it, its column types and the
    source aliases it was built from."""

    def __init__(self, names, types, members):
        self.names = set(names)
        self.types = dict(types)
        self.members = set(members)


class _Side:
    def __init__(self, tag, relation, qualifiers):
        self.tag = tag
        self.relation = relation
        self.qualifiers = qualifiers


class PairRow:
    """Row view over a (left, right) pair; a missing side reads as all-null."""

    __slots__ = ("left", "right")

    def __init__(self, left, right):
        self.left = left
        self.right = right

    def __getitem__(self, key):
        row = self.left if key[0] == LEFT else self.right
        return None if row is None else row[key[2:]]


# --------------------------------------------------------------------------- typing


def check(program, alias_types, params):
    """Type the with blocks and joins; returns the working schema after the final join.

    `alias_types` maps each source alias to the typed environment of its source.
    """
    relations = {alias: Relation({alias}, types, {alias}) for alias, types in alias_types.items()}
    blocks = {}
    for block in program.with_blocks:
        blocks.setdefault(block.alias, []).append(block)
    for alias in alias_types:
        for block in blocks.get(alias, ()):
            _check_block(block, relations[alias], params)

    previous = None
    for join in program.joins:
        left = _side(LEFT, join.left, relations, previous)
        right = _side(RIGHT, join.right, relations, previous)
        types = _check_join(join, left, right, params)
        names = {CURRENT_RELATION} | ({join.alias} if join.alias else set())
        result = Relation(names, types, left.relation.members | right.relation.members)
        if join.alias is not None:
            relations[join.alias] = result
            for block in blocks.get(join.alias, ()):
                _check_block(block, result, params)
        previous = result
    return previous.types


def _side(tag, name, relations, previous):
    if name == CURRENT_RELATION:
        return _Side(tag, previous, previous.names)
    relation = relations[name]
    return _Side(tag, relation, {name})


def _check_block(block, relation, params):
    types = relation.types
    for expr, line in [(c.expr, c.line) for c in block.calcs] + \
            [(f.predicate, f.line) for f in block.filters]:
        for node in walk(expr):
            if isinstance(node, ColumnRef) and node.qualifier is not None:
                if node.qualifier not in relation.names:
                    raise DSLSyntaxError(f"line {line}: '{node.qualifier}.{node.name}' is out "
                                         f"of scope in with block '{block.alias}'")
                node.qualifier = None
    for idx, calc in enumerate(block.calcs):
        if calc.name in types:
            raise DSLSyntaxError(f"line {calc.line}: calc '{calc.name}' collides with an "
                                 f"existing field of '{block.alias}'")
        check_names(calc.expr, types, params, line=calc.line,
                    later={c.name for c in block.calcs[idx + 1:]})
        check_declared(calc.name, calc.declared_type, infer(calc.expr, types, params), calc.line)
        types[calc.name] = calc.declared_type
    for flt in block.filters:
        check_names(flt.predicate, types, params, line=flt.line)
        t = infer(flt.predicate, types, params)
        if t != dtypes.BOOL:
            raise TypeCheckError(f"line {flt.line}: filter predicate must be boolean, got {t}")


def _check_join(join, left, right, params):
    sides = (left, right)
    env = {}
    for side in sides:
        for col, t in side.relation.types.items():
            env[side.tag + _SEP + col] = t

    _resolve(join.on, sides, join.line)
    check_names(join.on, env, params, line=join.line)
    t = infer(join.on, env, params)
    if t != dtypes.BOOL:
        raise TypeCheckError(f"line {join.line}: join condition must be boolean, got {t}")
    join.keys = _equi_keys(join.on)

    if join.within is not None:
        for side in sides:
            if side.relation.types.get(EVENT_TIME) != dtypes.TIMESTAMP:
                raise DSLSyntaxError(f"line {join.line}: 'within' requires a timestamp column "
                                     f"on both sides of the join")

    types = {}
    for proj in join.projections:
        _resolve(proj.expr, sides, proj.line)
        check_names(proj.expr, env, params, line=proj.line)
        proj.type = infer(proj.expr, env, params)
        types[proj.name] = proj.type

    if EVENT_TIME not in types:
        has_left = EVENT_TIME in left.relation.types
        has_right = EVENT_TIME in right.relation.types
        if has_left and has_right:
            raise TypeCheckError(f"line {join.line}: ambiguous timestamp: both sides of the join "
                                 "have 'timestamp'; project one of them as timestamp")
        if not has_left:
            raise TypeCheckError(f"line {join.line}: join result has no 'timestamp' column")
        ref = ColumnRef(LEFT + _SEP + EVENT_TIME, join.line)
        ref.type = left.relation.types[EVENT_TIME]
        proj = Projection(ref, EVENT_TIME, join.line)
        proj.type = ref.type
        join.projections.append(proj)
        types[EVENT_TIME] = proj.type
    if types[EVENT_TIME] != dtypes.TIMESTAMP:
        raise TypeCheckError(f"line {join.line}: projected 'timestamp' must be of type "
                             f"timestamp, got {types[EVENT_TIME]}")
    return types


def _resolve(expr, sides, line):
    """Bind each column reference to one join side, renaming it to its pair-row key."""
    for node in walk(expr):
        if not isinstance(node, ColumnRef):
            continue
        if node.qualifier is not None:
            matches = [s for s in sides if node.qualifier in s.qualifiers]
            if not matches:
                matches = [s for s in sides if node.qualifier in s.relation.members]
            if not matches:
                raise DSLSyntaxError(f"line {line}: unknown alias '{node.qualifier}' in "
                                     f"'{node.qualifier}.{node.name}'")
            if len(matches) > 1:
                raise DSLSyntaxError(f"line {line}: alias '{node.qualifier}' is ambiguous in "
                                     "this join")
            side = matches[0]
            if node.name not in side.relation.types:
                raise TypeCheckError(f"line {line}: unknown column "
                                     f"'{node.qualifier}.{node.name}'")
        else:
            matches = [s for s in sides if node.name in s.relation.types]
            if not matches:
                raise TypeCheckError(f"line {line}: unknown column '{node.name}'")
            if len(matches) > 1:
                raise DSLSyntaxError(f"line {line}: column '{node.name}' exists on both sides "
                                     "of the join; qualify it with an alias")
            side = matches[0]
        node.name = side.tag + _SEP + node.name
        node.qualifier = None


def _equi_keys(on):
    """(left_expr, right_expr) pairs of top-level `==` conjuncts usable as hash keys."""
    conjuncts = []
    stack = [on]
    while stack:
        node = stack.pop()
        if isinstance(node, Binary) and node.op == "&":
            stack.extend((node.right, node.left))
        else:
            conjuncts.append(node)
    keys = []
    for node in conjuncts:
        if not (isinstance(node, Binary) and node.op == "=="):
            continue
        a, b = _sides_of(node.left), _sides_of(node.right)
        if a == {LEFT} and b == {RIGHT}:
            keys.append((node.left, node.right))
        elif a == {RIGHT} and b == {LEFT}:
            keys.append((node.right, node.left))
    return keys


def _sides_of(expr):
    return {n.name[0] for n in walk(expr) if isinstance(n, ColumnRef)}


# --------------------------------------------------------------------------- execution


def run(program, source_rows, sink):
    """Apply with blocks and joins to the per-alias (Origin, row) lists; returns the
    final relation's (Origin, row) pairs."""
    blocks = {}
    for block in program.with_blocks:
        blocks.setdefault(block.alias, []).append(block)
    relations = {}
    for alias, rows in source_rows.items():
        relations[alias] = _apply_blocks(rows, blocks.get(alias, ()), sink)

    previous = None
    for join in program.joins:
        left = previous if join.left == CURRENT_RELATION else relations[join.left]
        right = previous if join.right == CURRENT_RELATION else relations[join.right]
        result = _join(join, left, right, sink)
        if join.alias is not None:
            result = _apply_blocks(result, blocks.get(join.alias, ()), sink)
            relations[join.alias] = result
        previous = result

    final = []
    for origin, row in previous:
        if row.get(EVENT_TIME) is None:
            sink.reject(BadRecord(origin, br.MISSING_REQUIRED_FIELD,
                                  "required field 'timestamp' is null after join projection",
                                  {"record": _show_row(row)}))
            continue
        final.append((origin, row))
    return final


def _apply_blocks(rows, blocks, sink):
    for block in blocks:
        calcs = [(c.name, c.expr, c.declared_type) for c in block.calcs]
        rows = transform_rows(rows, calcs, block.filters, sink)
    return rows


_ROW_ERRORS = (RuntimeFailure, ArithmeticError, ValueError, TypeError, RecursionError)


def _join(join, left_rows, right_rows, sink):
    within = timedelta(seconds=join.within) if join.within is not None else None
    keyed = bool(join.keys)
    index = {}
    if keyed:
        for j, (origin, row) in enumerate(right_rows):
            key = _key([k[1] for k in join.keys], PairRow(None, row), origin, sink)
            if key is not None:
                index.setdefault(key, []).append(j)
    everything = range(len(right_rows))
    matched_right = [False] * len(right_rows)
    keep_left = join.join_type in ("left", "full")
    keep_right = join.join_type in ("right", "full")

    out = []
    for origin, lrow in left_rows:
        if keyed:
            key = _key([k[0] for k in join.keys], PairRow(lrow, None), origin, sink)
            candidates = () if key is None else index.get(key, ())
        else:
            candidates = everything
        found = False
        for j in candidates:
            rrow = right_rows[j][1]
            if within is not None and not _within(lrow, rrow, within):
                continue
            try:
                ok = evaluate(join.on, PairRow(lrow, rrow)) is True
            except _ROW_ERRORS as exc:
                _reject(sink, origin, exc, lrow)
                continue
            if ok:
                found = True
                matched_right[j] = True
                _emit(out, join, origin, lrow, rrow, sink)
        if not found and keep_left:
            _emit(out, join, origin, lrow, None, sink)
    if keep_right:
        for j, (origin, rrow) in enumerate(right_rows):
            if not matched_right[j]:
                _emit(out, join, origin, None, rrow, sink)
    return out


def _key(exprs, pair, origin, sink):
    try:
        values = tuple(evaluate(e, pair) for e in exprs)
    except _ROW_ERRORS as exc:
        _reject(sink, origin, exc, pair.left if pair.left is not None else pair.right)
        return None
    if any(v is None for v in values):
        return None
    return values


def _within(lrow, rrow, delta):
    lt = lrow.get(EVENT_TIME)
    rt = rrow.get(EVENT_TIME)
    if lt is None or rt is None:
        return False
    return abs(lt - rt) <= delta


def _emit(out, join, origin, lrow, rrow, sink):
    pair = PairRow(lrow, rrow)
    try:
        row = {p.name: coerce(evaluate(p.expr, pair), p.type) for p in join.projections}
    except _ROW_ERRORS as exc:
        _reject(sink, origin, exc, lrow if lrow is not None else rrow)
        return
    out.append((origin, row))


def _reject(sink, origin, exc, row):
    if isinstance(exc, TypeError):
        error_type, error_class = br.TYPE_ERROR, TypeCheckError
    else:
        error_type, error_class = br.RUNTIME_ERROR, RuntimeFailure
    message = exc.message if isinstance(exc, RuntimeFailure) else (str(exc) or type(exc).__name__)
    if isinstance(exc, RecursionError):
        message = "expression nesting too deep"
    sink.reject(BadRecord(origin, error_type, message, {"record": _show_row(row or {})},
                          error_class))


def _show_row(row):
    return {k: format_utc(v) if hasattr(v, "astimezone") else v for k, v in row.items()}
