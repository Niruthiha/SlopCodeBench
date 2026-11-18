"""Pipeline execution.

Secret: the execution strategy -- row steps run in program order, rollup
clauses act on the final rows; everything is type-checked before any row is
touched; rows are bucketed by (window, group key).
"""

from collections import namedtuple

from . import program as P
from . import valuetypes as T
from .aggregates import make_aggregate
from .errors import TypeCheckError
from .expressions import compile_expression
from .windowing import TumblingWindow

ResultRow = namedtuple("ResultRow", "window_start window_end keys values")


class ResultSet:
    """Rollup outcome handed to the renderer.

    windowed:      whether rows carry window bounds
    group_columns: group_by column names, in declared order (may be empty)
    group_types:   the value type of each group column
    aliases:       aggregate aliases
    scalar:        True when there is neither window nor group_by
    rows:          ResultRow list (keys align with group_columns, values by alias)
    """

    def __init__(self, windowed, group_columns, group_types, aliases, scalar, rows):
        self.windowed = windowed
        self.group_columns = tuple(group_columns)
        self.group_types = tuple(group_types)
        self.aliases = tuple(aliases)
        self.scalar = scalar
        self.rows = rows


class _Schema:
    """Static view of column types as the program evolves them."""

    def __init__(self, base):
        self._base = base
        self._overrides = {}

    def has(self, name):
        return name in self._overrides or self._base.has(name)

    def type_of(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return self._base.type_of(name)

    def define(self, name, value_type):
        self._overrides[name] = value_type


def _require_column(schema, name, context):
    if not schema.has(name):
        raise TypeCheckError("unknown column %r in %s" % (name, context))
    return schema.type_of(name)


def execute(program, dataset):
    schema = _Schema(dataset)
    steps = []
    for step in program.steps:
        if isinstance(step, P.Filter):
            compiled = compile_expression(step.predicate, schema)
            if not T.is_bool(compiled.type):
                raise TypeCheckError("filter expression must be boolean, got %s"
                                     % T.type_name(compiled.type))
            steps.append(("filter", compiled))
        else:
            compiled = compile_expression(step.expression, schema)
            schema.define(step.column, compiled.type)
            steps.append(("apply", step.column, compiled))

    group_columns = program.group_by.columns if program.group_by else ()
    group_types = [_require_column(schema, c, "group_by") for c in group_columns]

    window = None
    if program.window is not None:
        ts_type = _require_column(schema, "timestamp", "window")
        if not T.is_timestamp(ts_type):
            raise TypeCheckError("window requires 'timestamp' to be a timestamp, got %s"
                                 % T.type_name(ts_type))
        window = TumblingWindow(program.window.amount, program.window.unit)

    aggregates = []
    for item in program.aggregate.items:
        input_type = None
        if item.column is not None:
            input_type = _require_column(schema, item.column, "aggregate")
        aggregates.append((item, make_aggregate(item.function, input_type)))

    for step in steps:
        if step[0] == "filter":
            predicate = step[1].evaluate
            dataset = dataset.filter(lambda r, p=predicate: p(r) is True)
        else:
            dataset = dataset.derive(step[1], step[2].type, step[2].evaluate)

    buckets = {}
    for record in dataset.records():
        bounds = window.bounds(record.get("timestamp")) if window else (None, None)
        key = (bounds, tuple(record.get(c) for c in group_columns))
        buckets.setdefault(key, []).append(record)

    scalar = window is None and not group_columns
    if scalar and not buckets:
        buckets[((None, None), ())] = []

    rows = []
    for (bounds, keys), records in buckets.items():
        values = {}
        for item, aggregate in aggregates:
            if item.column is None:
                inputs = [True] * len(records)
            else:
                inputs = [r.get(item.column) for r in records]
            values[item.alias] = aggregate.compute(inputs)
        rows.append(ResultRow(bounds[0], bounds[1], keys, values))

    aliases = [item.alias for item in program.aggregate.items]
    return ResultSet(window is not None, group_columns, group_types, aliases, scalar, rows)
