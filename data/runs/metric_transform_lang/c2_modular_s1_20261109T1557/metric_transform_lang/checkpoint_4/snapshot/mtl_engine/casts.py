"""Explicit `cast(expr as type)` conversions: which are legal and how values convert."""
import math
from datetime import timedelta, timezone

from . import dtypes
from .errors import RuntimeFailure
from .timeutil import EPOCH, ONE_MICROSECOND, TimestampParser, format_utc

_ILLEGAL = {
    (dtypes.BOOL, dtypes.TIMESTAMP),
    (dtypes.TIMESTAMP, dtypes.BOOL),
}

# Parser used for string -> timestamp casts; the CLI installs one honouring --tz.
_timestamp_parser = TimestampParser(timezone.utc)


def set_timestamp_parser(parser):
    global _timestamp_parser
    _timestamp_parser = parser


def allowed(source, target):
    return (source, target) not in _ILLEGAL


def convert(value, source, target, line):
    """Convert a non-null value of type `source` to `target`; failures are runtime errors."""
    if value is None:
        return None
    if source == target:
        return value
    try:
        result = _convert(value, source, target)
    except (ValueError, OverflowError) as exc:
        raise RuntimeFailure(f"line {line}: cannot cast {_show(value)} "
                             f"from {source} to {target}: {exc}") from exc
    if isinstance(result, float) and not math.isfinite(result):
        raise RuntimeFailure(f"line {line}: cast produced a non-finite number")
    return result


def _convert(value, source, target):
    if target == dtypes.STRING:
        if source == dtypes.BOOL:
            return "true" if value else "false"
        if source == dtypes.TIMESTAMP:
            return format_utc(value)
        if source == dtypes.FLOAT:
            return repr(value)
        return str(value)
    if source == dtypes.STRING:
        if target == dtypes.TIMESTAMP:
            return _timestamp_parser.parse(value)
        return dtypes.parse_text(value.strip(), target)
    if target == dtypes.INT:
        if source == dtypes.TIMESTAMP:
            return (value - EPOCH) // timedelta(seconds=1)
        if source == dtypes.FLOAT:
            return math.trunc(value)
        return int(value)
    if target == dtypes.FLOAT:
        if source == dtypes.TIMESTAMP:
            return ((value - EPOCH) // ONE_MICROSECOND) / 1_000_000
        return float(value)
    if target == dtypes.BOOL:
        return value != 0
    if target == dtypes.TIMESTAMP:
        return EPOCH + timedelta(seconds=value)
    raise AssertionError(f"unhandled cast {source} -> {target}")


def _show(value):
    return repr(value) if isinstance(value, str) else str(value)
