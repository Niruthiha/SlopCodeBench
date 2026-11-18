"""Rejected-row bookkeeping: classification, strict-mode termination and JSONL output."""
import json

from .errors import IOFailure, RuntimeFailure, TypeCheckError

PARSE_TYPE_MISMATCH = "PARSE_TYPE_MISMATCH"
TIMESTAMP_PARSE_ERROR = "TIMESTAMP_PARSE_ERROR"
RUNTIME_ERROR = "RUNTIME_ERROR"
TYPE_ERROR = "TYPE_ERROR"
MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
PARQUET_TYPE_MISMATCH = "PARQUET_TYPE_MISMATCH"


class Origin:
    """Where a row came from: file path, 1-based line (text files) or row index (Parquet)."""

    def __init__(self, path, line=None, row_index=None):
        self.path = path
        self.line = line
        self.row_index = row_index

    def describe(self):
        if self.line is not None:
            return f"{self.path}:{self.line}"
        return f"{self.path} row {self.row_index}"

    def sort_key(self):
        return (self.path, self.line if self.line is not None else -1,
                self.row_index if self.row_index is not None else -1)


class BadRecord:
    def __init__(self, origin, error_type, message, context=None, error_class=None):
        self.origin = origin
        self.error_type = error_type
        self.message = message
        self.context = context or {}
        # The MTLError subclass raised for this record in strict mode.
        self.error_class = error_class or _DEFAULT_ERRORS[error_type]

    def to_json(self):
        return {
            "file": self.origin.path,
            "line": self.origin.line,
            "row_index": self.origin.row_index,
            "error_type": self.error_type,
            "error": self.error_type,
            "message": self.message,
            "context": self.context,
        }


_DEFAULT_ERRORS = {
    PARSE_TYPE_MISMATCH: TypeCheckError,
    TIMESTAMP_PARSE_ERROR: TypeCheckError,
    TYPE_ERROR: TypeCheckError,
    MISSING_REQUIRED_FIELD: TypeCheckError,
    PARQUET_TYPE_MISMATCH: TypeCheckError,
    RUNTIME_ERROR: RuntimeFailure,
}


class BadRecordSink:
    """Collects rejected rows; in strict mode the first one aborts the run."""

    def __init__(self, strict):
        self.strict = strict
        self.records = []

    def reject(self, record):
        self.records.append(record)
        if self.strict:
            raise record.error_class(f"{record.origin.describe()}: {record.error_type}: "
                                     f"{record.message}")

    def write(self, path):
        """Write the rejected rows as JSON Lines, sorted by file then line; no rows, no file."""
        if not path or not self.records:
            return
        ordered = sorted(self.records, key=lambda r: r.origin.sort_key())
        lines = [json.dumps(_sanitize(r.to_json()), ensure_ascii=False, allow_nan=False)
                 for r in ordered]
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(lines) + "\n")
        except OSError as exc:
            raise IOFailure(f"cannot write bad records '{path}': {exc}") from exc


def _sanitize(value):
    """Make a value JSON-safe: undecodable bytes become U+FFFD, non-JSON types become text."""
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    if isinstance(value, str):
        return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    if isinstance(value, float) and value != value:
        return "NaN"
    if isinstance(value, float) and value in (float("inf"), float("-inf")):
        return "Infinity" if value > 0 else "-Infinity"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)
