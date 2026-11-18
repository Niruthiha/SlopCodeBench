"""Normalization (row ordering, key ordering) and deterministic JSON serialization."""
import json
import math
from datetime import datetime

from .errors import RuntimeFailure
from .timeutil import format_utc


def build_document(program, buckets):
    """Produce the JSON-ready value according to the normalization rules."""
    aliases = sorted(item.alias for item in program.aggregate.items)
    group_cols = program.group_columns
    windowed = program.window is not None

    if not group_cols and not windowed:
        values = buckets[0].values
        return {alias: _json_value(values[alias]) for alias in aliases}

    ordered = sorted(buckets, key=_bucket_sort_key)
    records = []
    for bucket in ordered:
        record = {}
        if windowed:
            record["window_start"] = format_utc(bucket.window_start)
            record["window_end"] = format_utc(bucket.window_end)
        for col, value in zip(group_cols, bucket.group_key):
            record[col] = _json_value(value)
        for alias in aliases:
            record[alias] = _json_value(bucket.values[alias])
        records.append(record)
    return records


def _bucket_sort_key(bucket):
    start = bucket.window_start
    window_part = (0,) if start is None else (1, start)
    return (window_part, tuple(_value_sort_key(v) for v in bucket.group_key))


def _value_sort_key(value):
    # Nulls sort first; within a column all non-null values share one kind.
    if value is None:
        return (0, 0)
    return (1, value)


def _json_value(value):
    if isinstance(value, datetime):
        return format_utc(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise RuntimeFailure("result contains a non-finite number")
    return value


def serialize(document):
    return json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
