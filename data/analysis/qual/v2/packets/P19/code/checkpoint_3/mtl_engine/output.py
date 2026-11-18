"""Normalization (row ordering, key ordering) and deterministic JSON serialization."""
import json
import math
from datetime import datetime

from .errors import RuntimeFailure
from .timeutil import format_utc


def build_document(program, buckets):
    """Produce the JSON-ready value from normalized-order buckets.

    Keys: window bounds, group keys, aggregate aliases (sorted), then
    post-aggregation calcs (sorted).
    """
    aliases = sorted(item.alias for item in program.aggregate.items)
    calc_names = sorted(calc.name for calc in program.post_calcs)
    group_cols = program.group_columns
    windowed = program.window is not None

    if not group_cols and not windowed:
        bucket = buckets[0]
        record = {alias: _json_value(bucket.values[alias]) for alias in aliases}
        for name in calc_names:
            record[name] = _json_value(bucket.calcs[name])
        return record

    records = []
    for bucket in buckets:
        record = {}
        if windowed:
            record["window_start"] = format_utc(bucket.window_start)
            record["window_end"] = format_utc(bucket.window_end)
        for col, value in zip(group_cols, bucket.group_key):
            record[col] = _json_value(value)
        for alias in aliases:
            record[alias] = _json_value(bucket.values[alias])
        for name in calc_names:
            record[name] = _json_value(bucket.calcs[name])
        records.append(record)
    return records


def _json_value(value):
    if isinstance(value, datetime):
        return format_utc(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise RuntimeFailure("result contains a non-finite number")
    return value


def serialize(document):
    return json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
