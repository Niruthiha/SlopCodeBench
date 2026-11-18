"""Executes a type-checked Program over typed rows, producing aggregated buckets."""
from .ast_nodes import Apply, Filter
from .aggregates import compute
from .evaluator import evaluate
from .timeutil import epoch_micros, from_epoch_micros

_MICROS_PER_SECOND = 1_000_000


class Bucket:
    """One output record before formatting: window bounds, group key and aggregate values."""

    def __init__(self, window_start, window_end, group_key, values):
        self.window_start = window_start
        self.window_end = window_end
        self.group_key = group_key
        self.values = values


def run(program, rows):
    """Return a list of Buckets (unordered)."""
    rows = apply_row_ops(program.row_ops, rows)
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


def apply_row_ops(row_ops, rows):
    """Run filter/apply statements in order; returns new row dicts."""
    current = [dict(r) for r in rows]
    for op in row_ops:
        if isinstance(op, Filter):
            current = [r for r in current if evaluate(op.predicate, r) is True]
        elif isinstance(op, Apply):
            for r in current:
                r[op.column] = evaluate(op.expr, r)
    return current


def _aggregate(program, rows):
    return {item.alias: compute(item, rows) for item in program.aggregate.items}
