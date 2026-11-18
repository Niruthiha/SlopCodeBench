"""Reads the input files (CSV/TSV, optionally gzipped, and Parquet) into typed rows.

Every value is checked against its expected type; rows that cannot be loaded
are handed to a BadRecordSink (which aborts the run in strict mode) instead
of being yielded.
"""
import csv
import gzip
import io
import sys
import zlib
from datetime import datetime, time, timedelta, timezone

from . import badrecords as br
from . import dtypes, inputs
from .badrecords import BadRecord, Origin
from .errors import IOFailure, TypeCheckError
from .timeutil import EPOCH

REQUIRED_COLUMNS = {
    "timestamp": dtypes.TIMESTAMP,
    "location": dtypes.STRING,
    "item": dtypes.STRING,
    "price": dtypes.FLOAT,
    "quantity": dtypes.FLOAT,
    "unit": dtypes.STRING,
    "category": dtypes.STRING,
}

# The event-time column: a row without a value for it is rejected.
EVENT_TIME = "timestamp"

DEFAULT_NULLS = ("", "null", "NULL", "NaN")

_GZIP_MAGIC = b"\x1f\x8b"
_PARQUET_MAGIC = b"PAR1"
_NAIVE_EPOCH = datetime(1970, 1, 1)


def parse_null_markers(spec):
    """--nulls value -> set of markers; the empty field is always null."""
    if spec is None:
        return frozenset(DEFAULT_NULLS)
    return frozenset({m.strip() for m in spec.split(",")} | {""})


def read_text(path):
    """Read a whole text file ('-' means STDIN), mapping failures to bad_io."""
    try:
        if path == "-":
            return sys.stdin.read()
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise IOFailure(f"cannot read '{path}': {exc}") from exc


class LoadContext:
    """Settings shared by all sources: timestamp parsing, null markers, strictness."""

    def __init__(self, ts_parser, null_markers, strict):
        self.ts_parser = ts_parser
        self.tz = ts_parser.default_tz
        self.null_markers = null_markers
        self.strict = strict

    def is_null_text(self, raw):
        return raw.strip() in self.null_markers


# --------------------------------------------------------------------------- sources


class TextSource:
    """A delimited file: header plus (line, fields) records; fields is None for a record
    the CSV reader could not parse (its error message is kept instead)."""

    kind = "text"

    def __init__(self, path, header, header_line, records, file_format=inputs.CSV):
        self.path = path
        self.format = file_format
        self.header = header
        self.header_line = header_line
        self.records = records
        self.index = {name: idx for idx, name in enumerate(header)}

    @property
    def columns(self):
        return self.header

    @property
    def rows_read(self):
        return len(self.records)


class ParquetSource:
    kind = "parquet"
    format = inputs.PARQUET

    def __init__(self, path, table):
        self.path = path
        self.table = table
        self.columns = list(table.column_names)
        _check_columns(path, self.columns)

    @property
    def rows_read(self):
        return self.table.num_rows


def open_sources(files):
    return [open_source(f) for f in files]


def open_source(input_file):
    path = input_file.path
    data = _read_bytes(path)
    fmt = input_file.format
    if fmt == inputs.PARQUET or (fmt is None and data.startswith(_PARQUET_MAGIC)):
        return _open_parquet(path, data)
    if data.startswith(_GZIP_MAGIC):
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError, zlib.error) as exc:
            raise IOFailure(f"cannot decompress '{path}': {exc}") from exc
    text = data.decode("utf-8", "surrogateescape")
    if text.startswith("﻿"):
        text = text[1:]
    if fmt is None:
        first = text.split("\n", 1)[0]
        fmt = inputs.TSV if "\t" in first and "," not in first else inputs.CSV
    return _parse_delimited(path, text, "\t" if fmt == inputs.TSV else ",", fmt)


def _read_bytes(path):
    try:
        if path == inputs.STDIN:
            return sys.stdin.buffer.read()
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise IOFailure(f"cannot read '{path}': {exc}") from exc


def _open_parquet(path, data):
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - dependency is in requirements.txt
        raise IOFailure(f"cannot read Parquet '{path}': pyarrow is not installed") from exc
    try:
        table = pq.read_table(pa.BufferReader(data))
    except Exception as exc:  # pyarrow raises a variety of error types for corrupt files
        raise IOFailure(f"cannot read Parquet '{path}': {exc}") from exc
    return ParquetSource(path, table)


def _parse_delimited(path, text, delimiter, file_format):
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, quotechar='"',
                        doublequote=True, strict=True)
    header = None
    header_line = None
    records = []
    prev = 0
    while True:
        try:
            record = next(reader)
            error = None
        except StopIteration:
            break
        except csv.Error as exc:
            record, error = None, str(exc)
        start, prev = prev + 1, reader.line_num
        if record is not None and _is_blank(record):
            continue
        if header is None:
            if record is None:
                raise IOFailure(f"malformed header in '{path}' line {start}: {error}")
            header, header_line = [h.strip() for h in record], start
            continue
        records.append((start, record, error))
    if header is None:
        raise IOFailure(f"'{path}' has no header row")
    _check_columns(path, header)
    return TextSource(path, header, header_line, records, file_format)


def _is_blank(record):
    return not record or (len(record) == 1 and not record[0].strip())


def _check_columns(path, names):
    seen = set()
    for name in names:
        if not name:
            raise IOFailure(f"'{path}' has an empty column name")
        if name in seen:
            raise IOFailure(f"'{path}' has duplicate column '{name}'")
        seen.add(name)


# --------------------------------------------------------------------------- schema


def infer_fields(sources, ctx):
    """Bare-statement typing: the Part 1 columns plus every other column found in any
    source, typed from its values (int, float, bool, else string).

    Returns (fields, lenient) where lenient names inferred string columns that
    accept any Parquet type (values are rendered as text).
    """
    extras = {}
    for source in sources:
        for name in source.columns:
            if name in REQUIRED_COLUMNS:
                continue
            if source.kind == "text":
                idx = source.index[name]
                found = _infer_text_type(
                    fields[idx] for _, fields, _ in source.records
                    if fields is not None and len(fields) == len(source.header)
                    and not ctx.is_null_text(fields[idx]))
            else:
                found = _ARROW_TO_DSL.get(_arrow_kind(source.table.schema.field(name).type),
                                          dtypes.STRING)
            extras[name] = _unify(extras.get(name), found)
    fields = dict(REQUIRED_COLUMNS)
    lenient = set()
    for name in sorted(extras):
        fields[name] = extras[name] or dtypes.STRING
        if fields[name] == dtypes.STRING:
            lenient.add(name)
    return fields, lenient


def _infer_text_type(values):
    present = [v.strip() for v in values]
    if not present:
        return None
    for t in (dtypes.INT, dtypes.FLOAT, dtypes.BOOL):
        if all(dtypes.looks_like(v, t) for v in present):
            return t
    return dtypes.STRING


def _unify(a, b):
    if a is None or a == b:
        return b
    if b is None:
        return a
    if dtypes.is_numeric(a) and dtypes.is_numeric(b):
        return dtypes.FLOAT
    return dtypes.STRING


# --------------------------------------------------------------------------- rows


class _Bad(Exception):
    def __init__(self, error_type, message):
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def iter_rows(sources, fields, ctx, sink, lenient=()):
    """Yield (Origin, row) for every loadable row, in file then line order.

    `fields` maps field name -> DSL type; every row has all of them (absent
    columns are null). Rejected rows go to `sink`.
    """
    required = {EVENT_TIME} if fields.get(EVENT_TIME) == dtypes.TIMESTAMP else set()
    for source in sources:
        absent = [name for name in fields if name not in source.columns]
        if absent and ctx.strict:
            raise TypeCheckError(f"'{source.path}' is missing column(s): {', '.join(absent)}")
        if source.kind == "text":
            yield from _text_rows(source, fields, required, ctx, sink)
        else:
            yield from _parquet_rows(source, fields, required, ctx, sink, lenient)


def _text_rows(source, fields, required, ctx, sink):
    width = len(source.header)
    loaded = [(name, ftype, source.index.get(name)) for name, ftype in fields.items()]
    for line, record, error in source.records:
        origin = Origin(source.path, line=line)
        if record is None:
            sink.reject(BadRecord(origin, br.PARSE_TYPE_MISMATCH, f"malformed record: {error}",
                                  {"delimiter": _delimiter_name(source)}, IOFailure))
            continue
        if len(record) != width:
            error_type = br.MISSING_REQUIRED_FIELD if len(record) < width \
                else br.PARSE_TYPE_MISMATCH
            sink.reject(BadRecord(origin, error_type,
                                  f"record has {len(record)} fields, expected {width}",
                                  {"fields": record, "header": source.header}, IOFailure))
            continue
        row = {}
        for name, ftype, idx in loaded:
            raw = None if idx is None else record[idx]
            try:
                value = None if raw is None else _convert_text(raw, ftype, ctx)
                if value is None and name in required:
                    raise _Bad(br.MISSING_REQUIRED_FIELD,
                               f"required field '{name}' is "
                               + ("absent" if raw is None else "null"))
            except _Bad as bad:
                sink.reject(BadRecord(origin, bad.error_type,
                                      f"column '{name}': {bad.message}",
                                      {"column": name, "value": raw, "expected_type": ftype,
                                       "record": dict(zip(source.header, record))}))
                break
            row[name] = value
        else:
            yield origin, row


def _delimiter_name(source):
    return "tab" if source.path.lower().endswith((".tsv", ".tsv.gz")) else "comma"


def _convert_text(raw, ftype, ctx):
    text = raw.strip()
    if text in ctx.null_markers:
        return None
    if not raw.isascii() and any("\udc80" <= ch <= "\udcff" for ch in raw):
        raise _Bad(br.PARSE_TYPE_MISMATCH, "value is not valid UTF-8")
    if ftype == dtypes.STRING:
        return raw
    if ftype == dtypes.TIMESTAMP:
        try:
            return ctx.ts_parser.parse(text)
        except (ValueError, OverflowError) as exc:
            raise _Bad(br.TIMESTAMP_PARSE_ERROR,
                       f"invalid timestamp {raw!r}: {exc}") from exc
    if dtypes.is_numeric(ftype) and text.lower() == "nan":
        return None
    try:
        return dtypes.parse_text(text, ftype)
    except ValueError as exc:
        raise _Bad(br.PARSE_TYPE_MISMATCH, f"invalid {ftype} value {raw!r}: {exc}") from exc


# Parquet ------------------------------------------------------------------


_ARROW_TO_DSL = {
    "int": dtypes.INT,
    "float": dtypes.FLOAT,
    "decimal": dtypes.FLOAT,
    "bool": dtypes.BOOL,
    "string": dtypes.STRING,
    "binary": dtypes.STRING,
    "timestamp": dtypes.TIMESTAMP,
    "date": dtypes.TIMESTAMP,
    "null": None,
}

# DSL type -> Arrow kinds it accepts.
_ACCEPTS = {
    dtypes.INT: ("int",),
    dtypes.FLOAT: ("float", "int", "decimal"),
    dtypes.BOOL: ("bool",),
    dtypes.STRING: ("string", "binary"),
    dtypes.TIMESTAMP: ("timestamp", "date"),
}


def _arrow_kind(arrow_type):
    import pyarrow.types as pat

    if pat.is_dictionary(arrow_type):
        arrow_type = arrow_type.value_type
    checks = (
        ("bool", pat.is_boolean), ("int", pat.is_integer), ("float", pat.is_floating),
        ("decimal", pat.is_decimal), ("timestamp", pat.is_timestamp), ("date", pat.is_date),
        ("null", pat.is_null),
        ("string", lambda t: pat.is_string(t) or pat.is_large_string(t)
         or getattr(pat, "is_string_view", lambda _: False)(t)),
        ("binary", lambda t: pat.is_binary(t) or pat.is_large_binary(t)
         or pat.is_fixed_size_binary(t) or getattr(pat, "is_binary_view", lambda _: False)(t)),
    )
    for kind, check in checks:
        if check(arrow_type):
            return kind
    return "other"


def _parquet_rows(source, fields, required, ctx, sink, lenient):
    table = source.table
    columns = {}
    for name, ftype in fields.items():
        if name in source.columns:
            columns[name] = _parquet_column(table.column(name), ftype, ctx, name in lenient)
    for idx in range(table.num_rows):
        origin = Origin(source.path, row_index=idx)
        row = {}
        for name, ftype in fields.items():
            values = columns.get(name)
            value = None if values is None else values[idx]
            if value is None and name in required:
                value = _Bad(br.MISSING_REQUIRED_FIELD, f"required field '{name}' is "
                             + ("absent" if values is None else "null"))
            if isinstance(value, _Bad):
                sink.reject(BadRecord(origin, value.error_type,
                                      f"column '{name}': {value.message}",
                                      {"column": name, "value": getattr(value, "raw", None),
                                       "expected_type": ftype,
                                       "parquet_type": str(table.schema.field(name).type)
                                       if name in source.columns else None}))
                break
            row[name] = value
        else:
            yield origin, row


def _parquet_column(column, ftype, ctx, lenient):
    """Convert an Arrow column to Python values of `ftype`; failures become _Bad entries."""
    import pyarrow.types as pat

    arrow_type = column.type
    if pat.is_dictionary(arrow_type):
        column = column.cast(arrow_type.value_type)
        arrow_type = arrow_type.value_type
    kind = _arrow_kind(arrow_type)
    if kind == "null":
        return [None] * len(column)
    if kind not in _ACCEPTS[ftype]:
        if lenient:
            return [None if v is None else _as_text(v, ctx) for v in _pylist(column, kind, ctx)]
        return [None if v is None else _mismatch(v, arrow_type, ftype) for v in column.to_pylist()]
    values = _pylist(column, kind, ctx)
    if ftype == dtypes.STRING:
        return [None if isinstance(v, str) and ctx.is_null_text(v) else v for v in values]
    if ftype == dtypes.TIMESTAMP:
        return values
    if ftype == dtypes.FLOAT:
        return [_float_value(v) for v in values]
    return values


def _pylist(column, kind, ctx):
    import pyarrow as pa

    if kind == "timestamp":
        micros = column.cast(pa.int64()).to_pylist()
        return [None if v is None else _timestamp_value(v, column.type, ctx) for v in micros]
    values = column.to_pylist()
    if kind == "binary":
        return [None if v is None else _decode(v) for v in values]
    if kind == "date":
        return [None if v is None else _date_value(v, ctx) for v in values]
    return values


def _mismatch(value, arrow_type, ftype):
    bad = _Bad(br.PARQUET_TYPE_MISMATCH,
               f"Parquet type {arrow_type} cannot be read as {ftype} (value {value!r})")
    bad.raw = value
    return bad


def _as_text(value, ctx):
    if isinstance(value, _Bad):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        from .timeutil import format_utc
        return format_utc(value)
    text = str(value)
    return None if ctx.is_null_text(text) else text


def _decode(raw):
    try:
        return bytes(raw).decode("utf-8")
    except UnicodeDecodeError:
        bad = _Bad(br.PARQUET_TYPE_MISMATCH, "binary value is not valid UTF-8 text")
        bad.raw = repr(raw)
        return bad


def _float_value(value):
    if value is None or isinstance(value, _Bad):
        return value
    result = float(value)
    if result != result:
        return None  # NaN is a missing value
    if result in (float("inf"), float("-inf")):
        bad = _Bad(br.PARSE_TYPE_MISMATCH, f"non-finite float value {result}")
        bad.raw = repr(result)
        return bad
    return result


_UNIT_MICROS = {"s": (1_000_000, 1), "ms": (1000, 1), "us": (1, 1), "ns": (1, 1000)}


def _timestamp_value(raw, arrow_type, ctx):
    mul, div = _UNIT_MICROS[arrow_type.unit]
    micros = raw * mul // div
    try:
        if arrow_type.tz is not None:
            return EPOCH + timedelta(microseconds=micros)
        wall = _NAIVE_EPOCH + timedelta(microseconds=micros)
        return wall.replace(tzinfo=ctx.tz).astimezone(timezone.utc)
    except OverflowError:
        bad = _Bad(br.TIMESTAMP_PARSE_ERROR, f"timestamp value {raw} is out of range")
        bad.raw = raw
        return bad


def _date_value(value, ctx):
    try:
        return datetime.combine(value, time()).replace(tzinfo=ctx.tz).astimezone(timezone.utc)
    except OverflowError:
        bad = _Bad(br.TIMESTAMP_PARSE_ERROR, f"date value {value} is out of range")
        bad.raw = str(value)
        return bad


# --------------------------------------------------------------------------- mapped sources


class FieldPlan:
    """How one schema field of an ingest source is produced from a file's columns."""

    def __init__(self, name, ftype, cast=None, default=None, has_default=False):
        self.name = name
        self.type = ftype
        self.cast = cast
        self.default = default
        self.has_default = has_default


class SourcePlan:
    """Mapping rules of one ingest source: drop -> rename -> cast -> defaults -> required."""

    def __init__(self, fields, rename, drop, required):
        self.fields = fields
        self.rename = rename
        self.drop = frozenset(drop)
        self.required = required

    def column_map(self, columns):
        """Mapped field name -> raw column name for a file's columns."""
        mapped = {}
        for col in columns:
            if col not in self.drop and col not in self.rename:
                mapped[col] = col
        for col in columns:
            if col not in self.drop and col in self.rename:
                mapped[self.rename[col]] = col
        return mapped


def iter_mapped_rows(source, plan, ctx, sink):
    """Yield (Origin, row) for the loadable rows of one file of an ingest source."""
    columns = plan.column_map(source.columns)
    absent = [f.name for f in plan.fields if f.name not in columns and not f.has_default]
    if absent and ctx.strict:
        raise TypeCheckError(f"'{source.path}' is missing column(s): {', '.join(absent)}")
    if source.kind == "text":
        rows = _mapped_text_rows(source, plan, columns, ctx, sink)
    else:
        rows = _mapped_parquet_rows(source, plan, columns, ctx, sink)
    for origin, row, context in rows:
        missing = [name for name in plan.required if row[name] is None]
        if missing:
            sink.reject(BadRecord(origin, br.MISSING_REQUIRED_FIELD,
                                  f"required field(s) {', '.join(missing)} null after mapping",
                                  {"fields": missing, "record": context}))
            continue
        yield origin, row


def _finish(value, spec):
    """Conform a (cast) value to the schema type, then apply the default."""
    if value is not None and spec.cast is not None and spec.cast != spec.type:
        if spec.cast == dtypes.INT and spec.type == dtypes.FLOAT:
            value = float(value)
        else:
            raise _Bad(br.TYPE_ERROR, f"value cast to {spec.cast} does not conform to schema "
                                      f"type {spec.type}")
    if value is None and spec.has_default:
        return spec.default
    return value


def _mapped_text_rows(source, plan, columns, ctx, sink):
    width = len(source.header)
    loaded = [(spec, source.index.get(columns[spec.name]) if spec.name in columns else None)
              for spec in plan.fields]
    for line, record, error in source.records:
        origin = Origin(source.path, line=line)
        if record is None:
            sink.reject(BadRecord(origin, br.PARSE_TYPE_MISMATCH, f"malformed record: {error}",
                                  {"delimiter": _delimiter_name(source)}, IOFailure))
            continue
        if len(record) != width:
            error_type = br.MISSING_REQUIRED_FIELD if len(record) < width \
                else br.PARSE_TYPE_MISMATCH
            sink.reject(BadRecord(origin, error_type,
                                  f"record has {len(record)} fields, expected {width}",
                                  {"fields": record, "header": source.header}, IOFailure))
            continue
        context = dict(zip(source.header, record))
        row = {}
        for spec, idx in loaded:
            raw = None if idx is None else record[idx]
            try:
                value = None if raw is None else _convert_text(raw, spec.cast or spec.type, ctx)
                row[spec.name] = _finish(value, spec)
            except _Bad as bad:
                sink.reject(BadRecord(origin, bad.error_type,
                                      f"field '{spec.name}': {bad.message}",
                                      {"column": spec.name, "value": raw,
                                       "expected_type": spec.cast or spec.type,
                                       "record": context}))
                break
        else:
            yield origin, row, context


def _mapped_parquet_rows(source, plan, columns, ctx, sink):
    table = source.table
    values = {}
    for spec in plan.fields:
        if spec.name in columns:
            column = table.column(columns[spec.name])
            if spec.cast is not None:
                values[spec.name] = _parquet_cast_column(column, spec.cast, ctx)
            else:
                values[spec.name] = _parquet_column(column, spec.type, ctx, False)
    for idx in range(table.num_rows):
        origin = Origin(source.path, row_index=idx)
        row = {}
        for spec in plan.fields:
            column_values = values.get(spec.name)
            value = None if column_values is None else column_values[idx]
            try:
                if isinstance(value, _Bad):
                    raise value
                row[spec.name] = _finish(value, spec)
            except _Bad as bad:
                raw = columns.get(spec.name)
                sink.reject(BadRecord(origin, bad.error_type,
                                      f"field '{spec.name}': {bad.message}",
                                      {"column": spec.name, "value": getattr(bad, "raw", None),
                                       "expected_type": spec.cast or spec.type,
                                       "parquet_type": str(table.schema.field(raw).type)
                                       if raw is not None else None}))
                break
        else:
            yield origin, row, {k: _context_value(v) for k, v in row.items()}


def _context_value(value):
    if isinstance(value, datetime):
        from .timeutil import format_utc
        return format_utc(value)
    return value


def _parquet_cast_column(column, target, ctx):
    """Arrow column -> Python values converted to `target` with cast() semantics."""
    import pyarrow.types as pat

    from . import casts
    from .errors import RuntimeFailure

    arrow_type = column.type
    if pat.is_dictionary(arrow_type):
        column = column.cast(arrow_type.value_type)
        arrow_type = arrow_type.value_type
    kind = _arrow_kind(arrow_type)
    if kind == "null":
        return [None] * len(column)
    natural = _ARROW_TO_DSL.get(kind)
    if natural is None:
        return [None if v is None else _mismatch(v, arrow_type, target)
                for v in column.to_pylist()]
    if natural == target or (natural == dtypes.INT and target == dtypes.FLOAT):
        return _parquet_column(column, target, ctx, False)
    result = []
    for value in _pylist(column, kind, ctx):
        if value is None or isinstance(value, _Bad):
            result.append(value)
            continue
        if kind == "decimal":
            value = float(value)
        if isinstance(value, float) and value != value:
            result.append(None)
            continue
        if natural == dtypes.STRING and ctx.is_null_text(value):
            result.append(None)
            continue
        try:
            if natural == dtypes.STRING and target == dtypes.TIMESTAMP:
                result.append(ctx.ts_parser.parse(value))
            elif not casts.allowed(natural, target):
                raise ValueError(f"cannot cast {natural} to {target}")
            else:
                result.append(casts.convert(value, natural, target, 0))
        except (ValueError, OverflowError, RuntimeFailure) as exc:
            error_type = br.TIMESTAMP_PARSE_ERROR if target == dtypes.TIMESTAMP \
                else br.PARSE_TYPE_MISMATCH
            bad = _Bad(error_type, f"cannot cast {value!r} from {natural} to {target}: "
                                   f"{getattr(exc, 'message', exc)}")
            bad.raw = value if isinstance(value, (str, int, float, bool)) else str(value)
            result.append(bad)
    return result
