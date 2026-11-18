"""Aggregate functions over a bucket of rows (nulls are ignored, empty input -> null)."""
import math

from .errors import RuntimeFailure


def _sum(values):
    # fsum is exactly rounded, so float totals do not depend on row order.
    if all(isinstance(v, int) for v in values):
        return sum(values)
    return math.fsum(values)


def _average(values):
    return _sum(values) / len(values)


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _var(values):
    mean = _average(values)
    return math.fsum((v - mean) * (v - mean) for v in values) / len(values)


def _std(values):
    return math.sqrt(_var(values))


_FUNCTIONS = {
    "sum": _sum,
    "average": _average,
    "median": _median,
    "var": _var,
    "std": _std,
    "min": min,
    "max": max,
}


def compute(item, rows):
    """Compute one aggregate item over a list of row dicts."""
    if item.func == "count":
        if item.column is None:
            return len(rows)
        return sum(1 for r in rows if r[item.column] is not None)
    values = [r[item.column] for r in rows if r[item.column] is not None]
    if not values:
        return None
    try:
        result = _FUNCTIONS[item.func](values)
    except (OverflowError, ValueError) as exc:
        raise RuntimeFailure(f"{item.func}({item.column}) failed: {exc}") from exc
    if isinstance(result, float) and not math.isfinite(result):
        raise RuntimeFailure(f"{item.func}({item.column}) produced a non-finite number")
    return result
