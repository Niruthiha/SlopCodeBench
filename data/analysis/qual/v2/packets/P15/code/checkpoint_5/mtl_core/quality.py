"""Data-quality bookkeeping.

Secret: how rejected rows are classified, which failure category a bad
record maps to in strict mode, and the JSON Lines shape and ordering of the
bad-records report.
"""

import json
import math
from datetime import datetime

from .errors import ExecutionError, InputError, TypeCheckError

PARSE_TYPE_MISMATCH = "PARSE_TYPE_MISMATCH"
TIMESTAMP_PARSE_ERROR = "TIMESTAMP_PARSE_ERROR"
RUNTIME_ERROR = "RUNTIME_ERROR"
TYPE_ERROR = "TYPE_ERROR"
MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
PARQUET_TYPE_MISMATCH = "PARQUET_TYPE_MISMATCH"

_STRICT_ERRORS = {
    PARSE_TYPE_MISMATCH: TypeCheckError,
    TIMESTAMP_PARSE_ERROR: TypeCheckError,
    RUNTIME_ERROR: ExecutionError,
    TYPE_ERROR: TypeCheckError,
    MISSING_REQUIRED_FIELD: TypeCheckError,
    PARQUET_TYPE_MISMATCH: TypeCheckError,
}


class Provenance:
    """Where a row came from: file path, physical line (None for Parquet), row ordinal."""

    __slots__ = ("file", "line", "row")

    def __init__(self, file, line, row):
        self.file = file
        self.line = line
        self.row = row

    def describe(self):
        if self.line is not None:
            return "%s:%d" % (self.file, self.line)
        if self.row is not None:
            return "%s: row %d" % (self.file, self.row)
        return self.file


class BadRecord:
    """One rejected row.

    error: optional MtlError class raised for it in strict mode (defaults by
    classification).
    """

    def __init__(self, provenance, classification, message, context=None, error=None):
        self.provenance = provenance
        self.classification = classification
        self.message = message
        self.context = context or {}
        self.error = error or _STRICT_ERRORS[classification]

    def sort_key(self):
        p = self.provenance
        line = p.line if p.line is not None else -1
        return (p.file, line, p.row if p.row is not None else -1)

    def as_json(self):
        p = self.provenance
        obj = {
            "file": p.file,
            "line": p.line,
            "row": p.row,
            "error": self.classification,
            "message": self.message,
            "context": _json_safe(self.context),
        }
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _json_safe(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


class BadRecordLog:
    """Collects bad records; in strict mode the first one aborts the run."""

    def __init__(self, strict):
        self.strict = strict
        self.records = []

    def add(self, record):
        self.records.append(record)
        if self.strict:
            raise record.error("%s: %s: %s" % (record.provenance.describe(),
                                               record.classification, record.message))

    def write(self, path):
        """Write the JSON Lines report; nothing is created when there are no bad rows."""
        if not path or not self.records:
            return
        ordered = sorted(self.records, key=BadRecord.sort_key)
        text = "".join(r.as_json() + "\n" for r in ordered)
        try:
            with open(path, "wb") as handle:
                handle.write(text.encode("utf-8"))
        except OSError as exc:
            raise InputError("cannot write bad records %r: %s" % (path, exc.strerror or exc))
