"""Executes a type-checked Program over typed rows, producing ordered aggregated buckets."""
from datetime import datetime

from . import badrecords, dtypes
from .ast_nodes import Apply, Filter
from .aggregates import compute
from .errors import RuntimeFailure, TypeCheckError
from .evaluator import evaluate
from .timeutil import epoch_micros, format_utc, from_epoch_micros
from .typecheck import output_schema

_MICROS_PER_SECOND = 1_000_000


class Bucket:
    """One output record before formatting: window bounds, group key, aggregate values
    and post-aggregation calc values."""

    def __init__(self, window_start, window_end, group_key, values):
        self.window_start = window_start
        self.window_end = window_end
        self.group_key = group_key
        self.values = values
        self.calcs = {}


def run(program, records, schema_calcs=(), row_schema=None, sink=None):
    """Return the Buckets in normalized order, with post-agg calcs evaluated.

    `records` yields (Origin, row) pairs; `schema_calcs` are the using-schema's
    calculated fields in evaluation order; `row_schema` is the checked row
    typing (needed for post-agg calcs). Rows whose row-level evaluation fails
    are handed to `sink` (when given) and skipped.
    """
    rows = prepare_rows(program, schema_calcs, records, sink)
    buckets = sorted(_bucketize(program, rows), key=bucket_sort_key)
    if program.post_calcs:
        _post_aggregate(program, buckets, row_schema or {})
    return buckets


def prepare_rows(program, schema_calcs, records, sink=None):
    """Materialize calculated fields and run filter/apply statements row by row;
    returns the rows that survive the filters."""
    calcs = [(f.name, f.expr, f.type) for f in schema_calcs]
    calcs += [(c.name, c.expr, c.declared_type) for c in program.pre_calcs]
    return [row for _, row in transform_rows(records, calcs, program.row_ops, sink)]


def transform_rows(records, calcs, row_ops, sink=None):
    """Evaluate (name, expr, declared_type) calcs, then filter/apply statements, over
    (Origin, row) records; returns the surviving (Origin, row) pairs."""
    result = []
    for origin, row in records:
        try:
            out = _evaluate_row(dict(row), calcs, row_ops)
        except (RuntimeFailure, ArithmeticError, ValueError, RecursionError) as exc:
            if sink is None:
                raise
            _reject(sink, origin, badrecords.RUNTIME_ERROR, exc, RuntimeFailure, row)
            continue
        except TypeError as exc:
            if sink is None:
                raise
            _reject(sink, origin, badrecords.TYPE_ERROR, exc, TypeCheckError, row)
            continue
        if out is not None:
            result.append((origin, out))
    return result


def _evaluate_row(row, calcs, row_ops):
    """Return the transformed row, or None when a filter drops it (null counts as false)."""
    for name, expr, declared in calcs:
        row[name] = coerce(evaluate(expr, row), declared)
    for op in row_ops:
        if isinstance(op, Filter):
            if evaluate(op.predicate, row) is not True:
                return None
        elif isinstance(op, Apply):
            row[op.column] = evaluate(op.expr, row)
    return row


def _reject(sink, origin, error_type, exc, error_class, row):
    message = exc.message if isinstance(exc, RuntimeFailure) else (str(exc) or type(exc).__name__)
    if isinstance(exc, RecursionError):
        message = "expression nesting too deep"
    sink.reject(badrecords.BadRecord(origin, error_type, message,
                                     {"record": {k: _show(v) for k, v in row.items()}},
                                     error_class))


def _show(value):
    if isinstance(value, datetime):
        return format_utc(value)
    return value


def coerce(value, declared):
    """Widen int values of float-typed fields."""
    if declared == dtypes.FLOAT and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    return value


def _bucketize(program, rows):
    group_cols = program.group_columns
    window = program.window

    if not group_cols and window is None:
        return [Bucket(None, None, (), _aggregate(program, rows))]

    width = window.seconds * _MICROS_PER_SECOND if window else None
    buckets = {}
    for row in rows:
        start = None
        if width is not None:
            start = epoch_micros(row["timestamp"]) // width * width
        key = (start, tuple(row[c] for c in group_cols))
        buckets.setdefault(key, []).append(row)

    result = []
    for (start, group_key), bucket_rows in buckets.items():
        ws = we = None
        if start is not None:
            ws = from_epoch_micros(start)
            we = from_epoch_micros(start + width)
        result.append(Bucket(ws, we, group_key, _aggregate(program, bucket_rows)))
    return result


def _aggregate(program, rows):
    return {item.alias: compute(item, rows) for item in program.aggregate.items}


def bucket_sort_key(bucket):
    start = bucket.window_start
    window_part = (0,) if start is None else (1, start)
    return (window_part, tuple(_value_sort_key(v) for v in bucket.group_key))


def _value_sort_key(value):
    # Nulls sort first; within a column all non-null values share one kind.
    if value is None:
        return (0, 0)
    return (1, value)


def _post_aggregate(program, buckets, row_schema):
    """Evaluate post-agg calcs over the ordered buckets, one calc at a time."""
    types = output_schema(program, row_schema)
    frame_rows = []
    for bucket in buckets:
        row = {}
        if program.window is not None:
            row["window_start"] = bucket.window_start
            row["window_end"] = bucket.window_end
        row.update(zip(program.group_columns, bucket.group_key))
        row.update(bucket.values)
        frame_rows.append({name: coerce(value, types[name]) for name, value in row.items()})

    for calc in program.post_calcs:
        values = [coerce(evaluate(calc.expr, row, (frame_rows, idx)), calc.declared_type)
                  for idx, row in enumerate(frame_rows)]
        for row, bucket, value in zip(frame_rows, buckets, values):
            row[calc.name] = value
            bucket.calcs[calc.name] = value
