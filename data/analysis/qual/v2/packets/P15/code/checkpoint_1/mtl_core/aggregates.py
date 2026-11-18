"""Aggregate functions.

Secret: the numeric algorithm behind each aggregate (summation order, median
of even counts, population variance/deviation), their typing rules, null
skipping and the finiteness guarantee on results.
"""

import math

from . import valuetypes as T
from .errors import ExecutionError, TypeCheckError

_FUNCTIONS = ("average", "median", "sum", "count", "std", "var", "min", "max")


class Aggregate:
    """compute(values) -> number or None; values holds one entry per input row."""

    def __init__(self, function, keep_int):
        self._function = function
        self._keep_int = keep_int

    def compute(self, values):
        present = [v for v in values if v is not None]
        if self._function == "count":
            return len(present)
        if not present:
            return None
        result = getattr(self, "_" + self._function)(present)
        if isinstance(result, float):
            if not math.isfinite(result):
                raise ExecutionError("%s produced a non-finite value" % self._function)
            result += 0.0  # normalise -0.0
        return result

    def _sum(self, xs):
        total = 0 if self._keep_int else 0.0
        for x in xs:
            total += x if self._keep_int else float(x)
        return total

    def _average(self, xs):
        return _mean(xs)

    def _median(self, xs):
        ordered = sorted(float(x) for x in xs)
        n = len(ordered)
        mid = n // 2
        if n % 2:
            return ordered[mid]
        a, b = ordered[mid - 1], ordered[mid]
        m = (a + b) / 2
        return m if math.isfinite(m) else a / 2 + b / 2

    def _var(self, xs):
        mean = _mean(xs)
        total = 0.0
        for x in xs:
            d = float(x) - mean
            total += d * d
        return total / len(xs)

    def _std(self, xs):
        v = self._var(xs)
        return math.sqrt(v) if math.isfinite(v) else v

    def _min(self, xs):
        m = min(xs)
        return m if self._keep_int else float(m)

    def _max(self, xs):
        m = max(xs)
        return m if self._keep_int else float(m)


def _mean(xs):
    total = 0.0
    for x in xs:
        total += float(x)
    mean = total / len(xs)
    if not math.isfinite(mean):
        raise ExecutionError("average produced a non-finite value")
    return mean


def make_aggregate(function, input_type):
    """Build an aggregate; input_type is None for '*'."""
    if function not in _FUNCTIONS:
        raise TypeCheckError("unknown aggregate %r" % function)
    if input_type is None:
        if function != "count":
            raise TypeCheckError("%s(*) is not allowed; only count(*)" % function)
    elif not T.is_numeric(input_type):
        raise TypeCheckError("%s() requires a numeric column, got %s"
                             % (function, T.type_name(input_type)))
    keep_int = input_type is not None and T.is_int(input_type)
    return Aggregate(function, keep_int)
