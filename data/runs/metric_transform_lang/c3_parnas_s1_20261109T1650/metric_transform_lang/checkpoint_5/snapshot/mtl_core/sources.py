"""Event sources: CSV, TSV (optionally gzipped) and Parquet files.

Secret: the text dialects and encoding, gzip handling, how Parquet logical
types are read, null markers, how raw cells and Parquet values are
reconciled with the column types (and how failures are classified), the
fixed event columns used when no schema is declared, and how types of
undeclared columns are inferred across all files.
"""

import csv
import gzip
import io
import math
import re
import zlib
from collections import OrderedDict
from datetime import date, datetime, timedelta
from decimal import Decimal

from . import inputs
from . import quality as Q
from . import timestamps
from . import valuetypes as T
from .dataset import Dataset
from .errors import InputError

KNOWN = OrderedDict([
    ("timestamp", T.TIMESTAMP),
    ("location", T.STRING),
    ("item", T.STRING),
    ("price", T.FLOAT),
    ("quantity", T.FLOAT),
    ("unit", T.STRING),
    ("category", T.STRING),
])
DEFAULT_NULLS = ("null", "NULL", "NaN")

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.?\d*([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?)$")
_EPOCH_NAIVE = datetime(1970, 1, 1)
_UNIT_MICROS = {"s": (1000000, 1), "ms": (1000, 1), "us": (1, 1), "ns": (1, 1000)}


def parse_null_markers(text):
    """The --nulls value as a marker set (None means the defaults)."""
    if text is None:
        return frozenset(DEFAULT_NULLS)
    return frozenset(m.strip() for m in text.split(",") if m.strip() != "")


class _CellError(Exception):
    def __init__(self, classification, message):
        Exception.__init__(self, message)
        self.classification = classification
        self.message = message


# ---------------------------------------------------------------------------
# Reading files


class _TextTable:
    kind = "text"

    def __init__(self, path, header, rows):
        self.path = path
        self.columns = header
        self.rows = rows          # list of (line, cells)

    @property
    def rows_read(self):
        return len(self.rows)


class _Unsupported:
    """Placeholder for a Parquet value of a type no DSL type can hold."""

    def __init__(self, type_name):
        self.type_name = type_name

    def __str__(self):
        return "<%s>" % self.type_name


class _OutOfRange:
    def __init__(self, raw):
        self.raw = raw

    def __str__(self):
        return "<timestamp out of range: %s>" % self.raw


class _ParquetTable:
    kind = "parquet"

    def __init__(self, path, handle):
        self.path = path
        self._handle = handle
        names = []
        for name in handle.schema_arrow.names:
            if name not in names:
                names.append(name)
        self.columns = names
        self.nrows = handle.metadata.num_rows
        self.data = {}            # name -> (kind, values)

    @property
    def rows_read(self):
        return self.nrows

    def load(self, wanted, ts_parser):
        names = [n for n in self.columns if n in wanted]
        try:
            table = self._handle.read(columns=names) if names else None
        except Exception as exc:
            raise InputError("cannot read Parquet %r: %s" % (self.path, exc))
        if table is not None:
            self.nrows = table.num_rows
            for name in names:
                index = table.schema.get_field_index(name)
                if index < 0:
                    index = table.schema.names.index(name)
                self.data[name] = _parquet_values(table.column(index), ts_parser)
        self._handle = None


def read_file(entry):
    """Read and structurally validate one input file (an inputs.InputFile)."""
    if entry.format == inputs.PARQUET:
        return _open_parquet(entry.path, entry.data_path or entry.path)
    data = _read_bytes(entry.path, entry.data_path or entry.path)
    if entry.gzipped or data[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError, zlib.error) as exc:
            raise InputError("cannot decompress %r: %s" % (entry.path, exc))
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("%r is not valid UTF-8" % entry.path)
    delimiter = "\t" if entry.format == inputs.TSV else ","
    header, rows = _split(text, delimiter, entry.path)
    return _TextTable(entry.path, header, rows)


def _read_bytes(path, location):
    try:
        with open(location, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise InputError("cannot read %r: %s" % (path, exc.strerror or exc))


def _split(text, delimiter, path):
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, quotechar='"',
                        doublequote=True, strict=True)
    rows = []
    previous = 0
    try:
        for cells in reader:
            line = previous + 1
            previous = reader.line_num
            if not cells or (len(cells) == 1 and cells[0].strip() == ""):
                continue
            rows.append((line, cells))
    except csv.Error as exc:
        raise InputError("malformed %s %r near line %d: %s"
                         % ("TSV" if delimiter == "\t" else "CSV", path, reader.line_num, exc))
    if not rows:
        raise InputError("%r has no header row" % path)
    header = [h.strip() for h in rows[0][1]]
    if any(h == "" for h in header):
        raise InputError("%r: header contains an empty column name" % path)
    if len(set(header)) != len(header):
        raise InputError("%r: header contains duplicate column names" % path)
    return header, rows[1:]


def _open_parquet(path, location):
    try:
        import pyarrow.parquet as pq
    except ImportError:  # pragma: no cover
        raise InputError("Parquet support requires pyarrow")
    try:
        handle = pq.ParquetFile(location)
        return _ParquetTable(path, handle)
    except Exception as exc:
        raise InputError("cannot read Parquet %r: %s" % (path, exc))


def _parquet_values(chunked, ts_parser):
    """(kind, python values) of one Parquet column; kind names the logical type."""
    import pyarrow as pa
    if chunked.num_chunks == 1:
        arr = chunked.chunk(0)
    elif chunked.num_chunks == 0:
        arr = pa.array([], chunked.type)
    else:
        arr = pa.concat_arrays(chunked.chunks)
    t = arr.type
    if pa.types.is_dictionary(t):
        arr = arr.dictionary_decode()
        t = arr.type
    if pa.types.is_timestamp(t):
        scale, divisor = _UNIT_MICROS[t.unit]
        raw = arr.cast(pa.int64()).to_pylist()
        values = [None if v is None else _instant(v * scale // divisor, t.tz is not None,
                                                  ts_parser) for v in raw]
        return "timestamp", values
    if pa.types.is_date(t):
        return "date", arr.to_pylist()
    if pa.types.is_boolean(t):
        return "bool", arr.to_pylist()
    if pa.types.is_integer(t):
        return "int", arr.to_pylist()
    if pa.types.is_floating(t):
        if t != pa.float64():
            arr = arr.cast(pa.float64())
        return "float", arr.to_pylist()
    if pa.types.is_decimal(t):
        return "decimal", arr.to_pylist()
    if pa.types.is_string(t) or pa.types.is_large_string(t) or _is(pa, "is_string_view", t):
        return "string", arr.to_pylist()
    if (pa.types.is_binary(t) or pa.types.is_large_binary(t)
            or pa.types.is_fixed_size_binary(t) or _is(pa, "is_binary_view", t)):
        return "binary", arr.to_pylist()
    if pa.types.is_null(t):
        return "null", [None] * len(arr)
    nulls = arr.is_null().to_pylist()
    marker = _Unsupported(str(t))
    return "other", [None if n else marker for n in nulls]


def _is(pa, predicate, t):
    test = getattr(pa.types, predicate, None)
    return bool(test and test(t))


def _instant(micros, aware, ts_parser):
    try:
        if aware:
            return timestamps.from_epoch_micros(micros)
        return ts_parser.localize(_EPOCH_NAIVE + timedelta(microseconds=micros))
    except Exception:
        return _OutOfRange(micros)


# ---------------------------------------------------------------------------
# Value conversion


class _Converter:
    """Turns raw cells / Parquet values into values of one column type."""

    def __init__(self, col_type, nulls, ts_parser):
        self.type = col_type
        self.nulls = nulls
        self.ts_parser = ts_parser
        self.iso_parser = ts_parser.iso_only()

    def text(self, cell, parser=None):
        stripped = cell.strip()
        if cell == "" or stripped in self.nulls:
            return None
        col_type = self.type
        if col_type == T.STRING:
            return cell
        if stripped == "":
            return None
        if col_type in (T.INT, T.FLOAT) and stripped.lower() == "nan":
            return None
        if col_type == T.INT:
            if not _INT_RE.match(stripped):
                raise _CellError(Q.PARSE_TYPE_MISMATCH, "value %r is not a valid int" % cell)
            return int(stripped)
        if col_type == T.FLOAT:
            if not _FLOAT_RE.match(stripped):
                raise _CellError(Q.PARSE_TYPE_MISMATCH, "value %r is not a valid float" % cell)
            value = float(stripped)
            if not math.isfinite(value):
                raise _CellError(Q.PARSE_TYPE_MISMATCH, "value %r is out of range for float"
                                 % cell)
            return value
        if col_type == T.BOOL:
            lowered = stripped.lower()
            if lowered not in ("true", "false"):
                raise _CellError(Q.PARSE_TYPE_MISMATCH, "value %r is not a valid bool" % cell)
            return lowered == "true"
        try:
            return (parser or self.ts_parser).parse(stripped)
        except (ValueError, OverflowError) as exc:
            raise _CellError(Q.TIMESTAMP_PARSE_ERROR, "value %r is not a valid timestamp (%s)"
                             % (cell, exc))

    def parquet(self, kind, value):
        """Reconcile a Parquet value of logical `kind` with the column type."""
        if value is None:
            return None
        col_type = self.type
        if kind == "string":
            try:
                return self.text(value, self.iso_parser)
            except _CellError as err:
                raise _CellError(Q.PARQUET_TYPE_MISMATCH,
                                 "Parquet string cannot be read as %s: %s" % (col_type, err))
        if kind == "binary" and col_type == T.STRING:
            try:
                return self.text(bytes(value).decode("utf-8"))
            except UnicodeDecodeError:
                pass
        elif col_type == T.INT:
            if kind == "int":
                return value
            if kind == "decimal" and value.is_finite() and value == value.to_integral_value():
                return int(value)
        elif col_type == T.FLOAT:
            if kind in ("int", "float", "decimal"):
                result = float(value)
                if math.isnan(result):
                    return None
                if math.isfinite(result):
                    return result
        elif col_type == T.BOOL:
            if kind == "bool":
                return value
        elif col_type == T.TIMESTAMP:
            if kind == "timestamp" and isinstance(value, datetime):
                return value
            if kind == "date" and isinstance(value, date):
                try:
                    return self.ts_parser.localize(datetime(value.year, value.month, value.day))
                except (OverflowError, ValueError):
                    pass
        raise _CellError(Q.PARQUET_TYPE_MISMATCH, "Parquet %s value %s cannot be read as %s"
                         % (kind, _show(value), col_type))


def _show(value):
    if isinstance(value, (datetime, date, Decimal, _Unsupported, _OutOfRange)):
        return str(value)
    return repr(value)


def _canonical_text(kind, value):
    """Text form of a Parquet value, for columns whose type is inferred from text."""
    if value is None:
        return ""
    if kind == "bool":
        return "true" if value else "false"
    if kind == "timestamp" and isinstance(value, datetime):
        return timestamps.format_utc(value)
    if kind == "float":
        return repr(value)
    if kind == "binary":
        return bytes(value).decode("utf-8", "replace")
    return str(value)


_KIND_TYPES = {"int": T.INT, "float": T.FLOAT, "decimal": T.FLOAT, "bool": T.BOOL,
               "string": T.STRING, "binary": T.STRING, "timestamp": T.TIMESTAMP,
               "date": T.TIMESTAMP, "other": T.STRING}


def _infer_text(cells, nulls, ts_parser):
    present = [c.strip() for c in cells if c.strip() != "" and c.strip() not in nulls]
    if not present:
        return T.STRING
    if all(_INT_RE.match(c) for c in present):
        return T.INT
    numeric = [c for c in present if c.lower() != "nan"]
    if numeric and all(_FLOAT_RE.match(c) for c in numeric):
        return T.FLOAT
    if all(c in ("true", "false") for c in present):
        return T.BOOL
    if all(ts_parser.looks_like_timestamp(c) for c in present):
        return T.TIMESTAMP
    return T.STRING


# ---------------------------------------------------------------------------
# Building the dataset


def load(entries):
    """Read every input file (structural checks only)."""
    return [read_file(e) for e in entries]


def build_dataset(tables, ts_parser, nulls, declared=None):
    """A Dataset over all tables.

    declared: name -> type of the schema's physical fields; when None the
    fixed event columns are used and other columns are exposed with
    inferred types.
    """
    if declared is not None:
        types = OrderedDict(declared)
        for table in tables:
            if table.kind == "parquet":
                table.load(set(types), ts_parser)
        plans = {}
    else:
        types = OrderedDict(KNOWN)
        extras = []
        for table in tables:
            for name in table.columns:
                if name not in types and name not in extras:
                    extras.append(name)
        for table in tables:
            if table.kind == "parquet":
                table.load(set(types) | set(extras), ts_parser)
        plans = {}
        for name in extras:
            types[name], plans[name] = _plan_extra(name, tables, nulls, ts_parser)
    converters = {name: _Converter(t, nulls, ts_parser) for name, t in types.items()}
    names = list(types)

    def entries():
        for table in tables:
            absent = [n for n in names if n not in table.columns]
            yield ("absent", table.path, absent)
            if table.kind == "parquet":
                rows = _parquet_rows(table, names, converters, plans)
            else:
                rows = _text_rows(table, names, converters)
            for item in rows:
                yield item

    return Dataset(names, [types[n] for n in names], entries)


def _plan_extra(name, tables, nulls, ts_parser):
    """(type, textual) for an undeclared column; textual means Parquet values go via text."""
    cells = []
    kinds = set()
    for table in tables:
        if name not in table.columns:
            continue
        if table.kind == "parquet":
            kind, _ = table.data[name]
            if kind != "null":
                kinds.add(kind)
        else:
            pos = table.columns.index(name)
            cells.extend(cells_[pos] for _, cells_ in table.rows if pos < len(cells_))
    present = [c for c in cells if c.strip() != "" and c.strip() not in nulls]
    if not present and kinds:
        mapped = {_KIND_TYPES[k] for k in kinds}
        if len(mapped) == 1:
            return mapped.pop(), False
        if mapped == {T.INT, T.FLOAT}:
            return T.FLOAT, False
    for table in tables:
        if table.kind == "parquet" and name in table.data:
            kind, values = table.data[name]
            cells.extend(_canonical_text(kind, v) for v in values if v is not None)
    return _infer_text(cells, nulls, ts_parser), True


def _text_rows(table, names, converters):
    header = table.columns
    width = len(header)
    positions = [(name, header.index(name) if name in header else None) for name in names]
    for ordinal, (line, cells) in enumerate(table.rows, start=1):
        prov = Q.Provenance(table.path, line, ordinal)
        if len(cells) != width:
            if len(cells) < width:
                classification = Q.MISSING_REQUIRED_FIELD
                message = "record has %d fields, expected %d (missing: %s)" % (
                    len(cells), width, ", ".join(header[len(cells):]))
            else:
                classification = Q.PARSE_TYPE_MISMATCH
                message = "record has %d fields, expected %d" % (len(cells), width)
            yield ("bad", Q.BadRecord(prov, classification, message,
                                      {"fields": list(cells), "header": list(header)},
                                      error=InputError))
            continue
        values = {}
        failure = None
        for name, pos in positions:
            if pos is None:
                values[name] = None
                continue
            converter = converters[name]
            try:
                values[name] = converter.text(cells[pos])
            except _CellError as err:
                failure = (name, cells[pos], converter.type, err)
                break
        if failure is None:
            yield ("row", prov, values)
            continue
        name, raw, col_type, err = failure
        yield ("bad", Q.BadRecord(prov, err.classification, "column %r: %s" % (name, err.message),
                                  {"column": name, "value": raw, "expected_type": col_type,
                                   "record": dict(zip(header, cells))}))


def _parquet_rows(table, names, converters, plans):
    columns = []
    for name in names:
        if name in table.data:
            kind, values = table.data[name]
            columns.append((name, kind, values))
        else:
            columns.append((name, None, None))
    for index in range(table.nrows):
        prov = Q.Provenance(table.path, None, index + 1)
        values = {}
        failure = None
        for name, kind, column in columns:
            if column is None:
                values[name] = None
                continue
            raw = column[index]
            converter = converters[name]
            try:
                if plans.get(name):
                    values[name] = (None if raw is None
                                    else converter.text(_canonical_text(kind, raw)))
                else:
                    values[name] = converter.parquet(kind, raw)
            except _CellError as err:
                failure = (name, raw, kind, converter.type, err)
                break
        if failure is None:
            yield ("row", prov, values)
            continue
        name, raw, kind, col_type, err = failure
        record = {n: (c[index] if c is not None else None) for n, _, c in columns}
        yield ("bad", Q.BadRecord(prov, err.classification, "column %r: %s" % (name, err.message),
                                  {"column": name, "value": raw, "parquet_type": kind,
                                   "expected_type": col_type, "record": record}))
