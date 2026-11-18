"""Loads the events CSV into typed rows plus a column-type schema."""
import csv
import io
import re
import sys

from . import dtypes
from .errors import IOFailure, TypeCheckError

REQUIRED_COLUMNS = {
    "timestamp": dtypes.TIMESTAMP,
    "location": dtypes.STRING,
    "item": dtypes.STRING,
    "price": dtypes.FLOAT,
    "quantity": dtypes.FLOAT,
    "unit": dtypes.STRING,
    "category": dtypes.STRING,
}

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_BOOLS = {"true": True, "false": False}


class Table:
    """Typed CSV contents: a schema (column -> type) and rows (list of dicts)."""

    def __init__(self, schema, rows):
        self.schema = schema
        self.rows = rows


def read_text(path):
    """Read a whole text file ('-' means STDIN), mapping failures to bad_io."""
    try:
        if path == "-":
            return sys.stdin.read()
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise IOFailure(f"cannot read '{path}': {exc}") from exc


def load_csv(path, ts_parser):
    text = read_text(path)
    if text.startswith("﻿"):
        text = text[1:]
    try:
        records = [r for r in csv.reader(io.StringIO(text, newline=""), strict=True) if r]
    except csv.Error as exc:
        raise IOFailure(f"malformed CSV '{path}': {exc}") from exc
    if not records:
        raise IOFailure(f"CSV '{path}' has no header row")

    header = [h.strip() for h in records[0]]
    _validate_header(header, path)
    body = records[1:]
    for lineno, record in enumerate(body, start=2):
        if len(record) != len(header):
            raise IOFailure(
                f"CSV '{path}' record {lineno} has {len(record)} fields, expected {len(header)}"
            )

    schema = {}
    for idx, name in enumerate(header):
        if name in REQUIRED_COLUMNS:
            schema[name] = REQUIRED_COLUMNS[name]
        else:
            schema[name] = _infer_type(r[idx] for r in body)

    converters = [_converter(name, schema[name], ts_parser) for name in header]
    rows = []
    for lineno, record in enumerate(body, start=2):
        row = {}
        for name, convert, raw in zip(header, converters, record):
            try:
                row[name] = convert(raw)
            except ValueError as exc:
                raise TypeCheckError(
                    f"CSV record {lineno}: invalid {schema[name]} value {raw!r} "
                    f"in column '{name}': {exc}"
                ) from exc
        rows.append(row)
    return Table(schema, rows)


def _validate_header(header, path):
    seen = set()
    for name in header:
        if not name:
            raise IOFailure(f"CSV '{path}' has an empty column name")
        if name in seen:
            raise IOFailure(f"CSV '{path}' has duplicate column '{name}'")
        seen.add(name)
    missing = [c for c in REQUIRED_COLUMNS if c not in seen]
    if missing:
        raise IOFailure(f"CSV '{path}' is missing required column(s): {', '.join(missing)}")


def _infer_type(values):
    present = [v.strip() for v in values if v.strip()]
    if not present:
        return dtypes.STRING
    if all(_INT_RE.match(v) for v in present):
        return dtypes.INT
    if all(_FLOAT_RE.match(v) for v in present):
        return dtypes.FLOAT
    if all(v.lower() in _BOOLS for v in present):
        return dtypes.BOOL
    return dtypes.STRING


def _converter(name, col_type, ts_parser):
    if col_type == dtypes.TIMESTAMP:
        return ts_parser.parse
    if col_type == dtypes.STRING:
        return lambda raw: raw
    if col_type == dtypes.INT:
        return _nullable(int)
    if col_type == dtypes.FLOAT:
        return _nullable(_parse_float)
    if col_type == dtypes.BOOL:
        return _nullable(lambda v: _BOOLS[v.lower()])
    raise AssertionError(f"unhandled column type {col_type} for {name}")


def _nullable(parse):
    def convert(raw):
        value = raw.strip()
        if not value:
            return None
        return parse(value)
    return convert


def _parse_float(value):
    if not _FLOAT_RE.match(value):
        raise ValueError("not a number")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("not a finite number")
    return result
