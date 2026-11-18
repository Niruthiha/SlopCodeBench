"""Pipeline execution.

Secret: the execution strategy -- schema-level and @stage(pre) calculated
fields materialise first, row steps then run in program order, rollup
clauses act on the final rows, result rows are put in their canonical order
and @stage(post_agg) calcs are evaluated over that order; everything is
type-checked before any row is touched; rows are bucketed by (window, group
key).
"""

import re
from collections import namedtuple

from . import program as P
from . import valuetypes as T
from .aggregates import make_aggregate, result_type
from . import quality as Q
from .errors import DslError, ExecutionError, TypeCheckError
from .expressions import coerce, column_references, compile_expression, is_assignable
from .quality import BadRecord, BadRecordLog, Provenance
from .windowing import TumblingWindow

ResultRow = namedtuple("ResultRow", "window_start window_end keys values")
_WINDOW_FIELDS = ("window_start", "window_end")


class ResultSet:
    """Rollup outcome handed to the renderer.

    windowed:      whether rows carry window bounds
    group_columns: group_by column names, in declared order (may be empty)
    group_types:   the value type of each group column
    aliases:       aggregate aliases
    scalar:        True when there is neither window nor group_by
    rows:          ResultRow list in output order (keys align with
                   group_columns, values by alias and calc name)
    calc_names:    post-aggregation calc names
    calc_types:    the value type of each post-aggregation calc
    """

    def __init__(self, windowed, group_columns, group_types, aliases, scalar, rows,
                 calc_names=(), calc_types=()):
        self.windowed = windowed
        self.group_columns = tuple(group_columns)
        self.group_types = tuple(group_types)
        self.aliases = tuple(aliases)
        self.scalar = scalar
        self.rows = rows
        self.calc_names = tuple(calc_names)
        self.calc_types = tuple(calc_types)


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


class _Names:
    """A plain name -> type mapping with the has/type_of protocol."""

    def __init__(self):
        self._types = {}

    def has(self, name):
        return name in self._types

    def type_of(self, name):
        return self._types[name]

    def define(self, name, value_type):
        self._types[name] = value_type


class _RowRecord:
    """One input row as seen by row-level expressions."""

    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data

    def get(self, name):
        return self.data[name]


class _OutputRecord:
    """One result row as seen by post-aggregation calcs."""

    __slots__ = ("data", "position", "table")

    def __init__(self, data, position, table):
        self.data = data
        self.position = position
        self.table = table

    def get(self, name):
        return self.data[name]


def _require_column(schema, name, context):
    if not schema.has(name):
        raise TypeCheckError("unknown column %r in %s" % (name, context))
    return schema.type_of(name)


def _sort_key(value):
    # Nulls sort first; values within one column share a type, so Python's
    # ordering gives numeric, code-point and chronological order respectively.
    return (0, 0) if value is None else (1, value)


def _check_declared(name, declared, compiled, what):
    if not is_assignable(declared, compiled.type):
        raise TypeCheckError("%s %r is declared %s but its expression is %s"
                             % (what, name, T.type_name(declared), T.type_name(compiled.type)))
    return coerce(declared, compiled)


def _window(program, params):
    spec = program.window
    if spec.param is None:
        return TumblingWindow(spec.amount, spec.unit)
    if spec.param not in params:
        raise DslError("unknown parameter %r" % spec.param)
    value_type, value = params[spec.param]
    m = re.match(r"^\s*(\d+)\s*([mhd])\s*$", value) if T.is_string(value_type) else None
    if not m or int(m.group(1)) <= 0:
        raise TypeCheckError("window parameter %r must be a duration like '1h', got %r"
                             % (spec.param, value))
    return TumblingWindow(int(m.group(1)), m.group(2))


def execute(program, dataset, schema_def=None, params=None, ts_parser=None, bad_records=None):
    params = params or {}
    schema = _Schema(dataset)
    row_ops = []

    def compile_for_rows(expr, unknown=None):
        return compile_expression(expr, schema, params, unknown=unknown, ts_parser=ts_parser)

    # Schema-level calculated fields.
    if schema_def is not None:
        def schema_unknown(name):
            return DslError("schema field references unknown field %r" % name)
        for field in schema_def.calcs:
            compiled = compile_for_rows(field.expression, schema_unknown)
            evaluate = _check_declared(field.name, field.type, compiled, "schema field")
            schema.define(field.name, field.type)
            row_ops.append(("derive", field.name, field.type, evaluate))

    # @stage(pre) calcs.
    aliases = [item.alias for item in program.aggregate.items]
    pre_names = [c.name for c in program.pre_calcs]
    post_names = [c.name for c in program.post_calcs]
    apply_targets = {s.column for s in program.steps if isinstance(s, P.Apply)}
    for index, calc in enumerate(program.pre_calcs):
        if schema.has(calc.name) or calc.name in apply_targets:
            raise DslError("calculated field %r collides with an existing field" % calc.name)
        later = set(pre_names[index + 1:])

        def pre_unknown(name, later=later):
            if name in aliases or name in post_names:
                return DslError("@stage(pre) calc cannot use aggregate output %r" % name)
            if name in later:
                return DslError("calc references %r before it is declared" % name)
            return TypeCheckError("unknown column %r" % name)
        compiled = compile_for_rows(calc.expression, pre_unknown)
        evaluate = _check_declared(calc.name, calc.type, compiled, "calc")
        schema.define(calc.name, calc.type)
        row_ops.append(("derive", calc.name, calc.type, evaluate))

    # Part 1 row steps.
    for step in program.steps:
        if isinstance(step, P.Filter):
            compiled = compile_for_rows(step.predicate)
            if not T.is_bool(compiled.type):
                raise TypeCheckError("filter expression must be boolean, got %s"
                                     % T.type_name(compiled.type))
            row_ops.append(("filter", compiled.evaluate))
        else:
            compiled = compile_for_rows(step.expression)
            schema.define(step.column, compiled.type)
            row_ops.append(("derive", step.column, compiled.type, compiled.evaluate))

    group_columns = program.group_by.columns if program.group_by else ()
    group_types = [_require_column(schema, c, "group_by") for c in group_columns]

    window = None
    if program.window is not None:
        ts_type = _require_column(schema, "timestamp", "window")
        if not T.is_timestamp(ts_type):
            raise TypeCheckError("window requires 'timestamp' to be a timestamp, got %s"
                                 % T.type_name(ts_type))
        window = _window(program, params)

    aggregates = []
    output_names = _Names()
    if window is not None:
        for name in _WINDOW_FIELDS:
            output_names.define(name, T.TIMESTAMP)
    for name, value_type in zip(group_columns, group_types):
        output_names.define(name, value_type)
    for item in program.aggregate.items:
        input_type = None
        if item.column is not None:
            input_type = _require_column(schema, item.column, "aggregate")
        aggregates.append((item, make_aggregate(item.function, input_type)))
        output_names.define(item.alias, result_type(item.function, input_type))

    # @stage(post_agg) calcs.
    post_calcs = []
    for index, calc in enumerate(program.post_calcs):
        if output_names.has(calc.name):
            raise DslError("calculated field %r collides with another output field" % calc.name)
        later = set(post_names[index + 1:])

        def post_unknown(name, later=later):
            if name in later:
                return DslError("calc references %r before it is declared" % name)
            return TypeCheckError("@stage(post_agg) calc references %r, which is not a "
                                  "group key, window bound, aggregate or earlier calc" % name)
        compiled = compile_expression(calc.expression, output_names, params, row_relative=True,
                                      unknown=post_unknown, ts_parser=ts_parser)
        evaluate = _check_declared(calc.name, calc.type, compiled, "calc")
        output_names.define(calc.name, calc.type)
        post_calcs.append((calc.name, evaluate))

    referenced = _referenced_columns(program, schema_def, group_columns, window is not None)
    buckets = _evaluate_rows(dataset, row_ops, window, group_columns, referenced,
                             bad_records if bad_records is not None else BadRecordLog(False))

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
                inputs = [r[item.column] for r in records]
            values[item.alias] = aggregate.compute(inputs)
        rows.append(ResultRow(bounds[0], bounds[1], keys, values))
    rows.sort(key=lambda r: (_sort_key(r.window_start), tuple(_sort_key(k) for k in r.keys)))

    if post_calcs:
        table = []
        for position, row in enumerate(rows):
            data = dict(row.values)
            data.update(zip(group_columns, row.keys))
            if window is not None:
                data["window_start"] = row.window_start
                data["window_end"] = row.window_end
            table.append(_OutputRecord(data, position, table))
        for name, evaluate in post_calcs:
            for record in table:
                record.data[name] = evaluate(record)
        for row, record in zip(rows, table):
            for name, _ in post_calcs:
                row.values[name] = record.data[name]

    post = program.post_calcs
    return ResultSet(window is not None, group_columns, group_types, aliases, scalar, rows,
                     [c.name for c in post], [c.type for c in post])


def _referenced_columns(program, schema_def, group_columns, windowed):
    """Input columns the pipeline reads (directly or via schema calcs)."""
    names = set(group_columns)
    exprs = [c.expression for c in program.pre_calcs]
    if schema_def is not None:
        exprs.extend(f.expression for f in schema_def.calcs)
    for step in program.steps:
        exprs.append(step.predicate if isinstance(step, P.Filter) else step.expression)
    for expr in exprs:
        names.update(column_references(expr))
    names.update(item.column for item in program.aggregate.items if item.column is not None)
    if windowed:
        names.add("timestamp")
    return names


def _apply_row_ops(row_ops, record):
    """Run the row steps on one record; False if a filter drops it."""
    data = record.data
    for op in row_ops:
        if op[0] == "filter":
            if op[1](record) is not True:
                return False
        else:
            data[op[1]] = op[3](record)
    return True


def _evaluate_rows(dataset, row_ops, window, group_columns, referenced, log):
    """Evaluate row steps row by row and bucket the surviving rows by (window, keys)."""
    buckets = {}
    for entry in dataset.entries():
        tag = entry[0]
        if tag == "absent":
            missing = [n for n in entry[2] if n in referenced]
            if missing and log.strict:
                log.add(BadRecord(Provenance(entry[1], None, None), Q.MISSING_REQUIRED_FIELD,
                                  "input lacks column(s) %s" % ", ".join(missing),
                                  {"columns": missing}))
            continue
        if tag == "bad":
            log.add(entry[1])
            continue
        prov, data = entry[1], entry[2]
        failure = None
        try:
            keep = _apply_row_ops(row_ops, _RowRecord(data))
        except TypeCheckError as exc:
            failure = (Q.TYPE_ERROR, str(exc))
        except ExecutionError as exc:
            failure = (Q.RUNTIME_ERROR, str(exc))
        except (ArithmeticError, ValueError) as exc:
            failure = (Q.RUNTIME_ERROR, "evaluation failed: %s" % exc)
        if failure is not None:
            log.add(BadRecord(prov, failure[0], failure[1], {"values": data}))
            continue
        if not keep:
            continue
        bounds = (None, None)
        if window is not None:
            instant = data.get("timestamp")
            if instant is None:
                log.add(BadRecord(prov, Q.MISSING_REQUIRED_FIELD,
                                  "timestamp is null; the row cannot be assigned to a window",
                                  {"column": "timestamp", "values": data}))
                continue
            try:
                bounds = window.bounds(instant)
            except ExecutionError as exc:
                log.add(BadRecord(prov, Q.RUNTIME_ERROR, str(exc), {"values": data}))
                continue
        key = (bounds, tuple(data[c] for c in group_columns))
        buckets.setdefault(key, []).append(data)
    return buckets
