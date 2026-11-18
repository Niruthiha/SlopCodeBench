"""CSV event source.

Secret: the CSV dialect and encoding, the fixed schema of the known event
columns (or the physical fields of a declared schema), how cells become
typed values, and how types of extra columns are inferred.
"""

import csv
import io
import re

from . import valuetypes as T
from .dataset import Dataset
from .errors import InputError, TypeCheckError

_KNOWN = {
    "timestamp": T.TIMESTAMP,
    "location": T.STRING,
    "item": T.STRING,
    "price": T.FLOAT,
    "quantity": T.FLOAT,
    "unit": T.STRING,
    "category": T.STRING,
}
_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.?\d*([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?)$")


def read_csv_text(path):
    """Read the raw file; I/O problems are reported as InputError."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise InputError("cannot read CSV %r: %s" % (path, exc.strerror or exc))
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("CSV %r is not valid UTF-8" % path)


def _split(text, required):
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        raise InputError("malformed CSV: %s" % exc)
    rows = [r for r in rows if r and not (len(r) == 1 and r[0].strip() == "")]
    if not rows:
        raise InputError("CSV has no header row")
    header = [h.strip() for h in rows[0]]
    if any(h == "" for h in header):
        raise InputError("CSV header contains an empty column name")
    if len(set(header)) != len(header):
        raise InputError("CSV header contains duplicate column names")
    missing = [c for c in required if c not in header]
    if missing:
        raise InputError("CSV is missing required column(s): %s" % ", ".join(missing))
    body = rows[1:]
    for lineno, row in enumerate(body, start=2):
        if len(row) != len(header):
            raise InputError("CSV record %d has %d fields, expected %d"
                             % (lineno, len(row), len(header)))
    return header, body


def _parse_float(text):
    try:
        return float(text.strip())
    except ValueError:
        raise ValueError(text)


def _parse_bool(text):
    lowered = text.strip().lower()
    if lowered not in ("true", "false"):
        raise ValueError(text)
    return lowered == "true"


def _infer(cells, ts_parser):
    present = [c.strip() for c in cells if c.strip() != ""]
    if not present:
        return T.STRING
    if all(_INT_RE.match(c) for c in present):
        return T.INT
    if all(_FLOAT_RE.match(c) for c in present):
        return T.FLOAT
    if all(c in ("true", "false") for c in present):
        return T.BOOL
    if all(ts_parser.looks_like_timestamp(c) for c in present):
        return T.TIMESTAMP
    return T.STRING


def _converter(col_type, ts_parser, required):
    def nullable(fn):
        def convert(cell):
            if cell.strip() == "":
                if required:
                    raise ValueError("empty value")
                return None
            return fn(cell)
        return convert

    if col_type == T.STRING:
        return lambda cell: cell
    if col_type == T.INT:
        return nullable(lambda c: int(c.strip()))
    if col_type == T.FLOAT:
        return nullable(_parse_float)
    if col_type == T.BOOL:
        return nullable(_parse_bool)
    return nullable(ts_parser.parse)


def build_dataset(text, ts_parser, declared=None):
    """Convert raw CSV text into a typed Dataset.

    declared: optional name -> type of schema fields that must be present;
    without it the fixed event columns are required.
    """
    header, body = _split(text, _KNOWN if declared is None else declared)
    declared = declared or {}
    types = []
    converters = []
    for pos, name in enumerate(header):
        required = name in _KNOWN
        if name in declared:
            col_type = declared[name]
        elif required:
            col_type = _KNOWN[name]
        else:
            col_type = _infer([r[pos] for r in body], ts_parser)
        types.append(col_type)
        converters.append(_converter(col_type, ts_parser, required))
    rows = []
    for lineno, raw in enumerate(body, start=2):
        row = []
        for name, col_type, convert, cell in zip(header, types, converters, raw):
            try:
                value = convert(cell)
            except (ValueError, OverflowError):
                raise TypeCheckError("CSV record %d: column %r value %r is not a valid %s"
                                     % (lineno, name, cell, T.type_name(col_type)))
            row.append(value)
        rows.append(row)
    return Dataset.from_rows(header, types, rows)


def load_csv(path, ts_parser):
    return build_dataset(read_csv_text(path), ts_parser)
