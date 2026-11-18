"""JSON rendering.

Secret: the JSON document shape, object key ordering and how
values (numbers, timestamps, nulls) are encoded.
"""

import json
import math
from collections import OrderedDict

from . import timestamps
from . import valuetypes as T
from .errors import ExecutionError


def _encode(value, value_type=None):
    if value is None:
        return None
    if value_type is not None and T.is_timestamp(value_type):
        return timestamps.format_utc(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ExecutionError("cannot emit non-finite number")
        return value + 0.0
    return value


def _object(result, row):
    obj = OrderedDict()
    if result.windowed:
        obj["window_start"] = timestamps.format_utc(row.window_start)
        obj["window_end"] = timestamps.format_utc(row.window_end)
    for name, value_type, value in zip(result.group_columns, result.group_types, row.keys):
        obj[name] = _encode(value, value_type)
    for alias in sorted(result.aliases):
        obj[alias] = _encode(row.values[alias])
    for name, value_type in sorted(zip(result.calc_names, result.calc_types)):
        obj[name] = _encode(row.values[name], value_type)
    return obj


def render(result):
    """Serialise a ResultSet to the deterministic JSON text."""
    if result.scalar:
        document = _object(result, result.rows[0])
    else:
        document = [_object(result, r) for r in result.rows]
    try:
        return json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    except ValueError as exc:
        raise ExecutionError("cannot emit result: %s" % exc)
