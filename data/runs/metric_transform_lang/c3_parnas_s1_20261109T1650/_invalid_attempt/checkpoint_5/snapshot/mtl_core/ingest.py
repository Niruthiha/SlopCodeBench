"""Declarative multi-source ingestion.

Secret: the ingest-config document (YAML or JSON) and its validation, how
source patterns are expanded and files assigned to sources by precedence,
and how each source's mapping (drop, rename, cast, defaults), schema
conversion, required-field checks and schema calcs turn raw file rows into
typed rows.
"""

import glob
import json
import math
import os
import re
from collections import OrderedDict, namedtuple
from datetime import date, datetime

from . import inputs
from . import quality as Q
from . import sources as S
from . import valuetypes as T
from .declarations import resolve_named_schema
from .dsl_parser import TYPE_NAMES
from .errors import ConfigError, ExecutionError, InputError, MtlError, TypeCheckError
from .expressions import cast_value, coerce, compile_expression, is_assignable
from .timestamps import TimestampParser

_SOURCE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAPPING_KEYS = ("drop", "rename", "cast", "defaults")

Defaults = namedtuple("Defaults", "tz timestamp_format nulls format recursive")

SourceSpec = namedtuple("SourceSpec", "name patterns recursive format schema precedence "
                                      "ts_parser nulls drop rename cast defaults required "
                                      "base_dir")
# patterns: path-or-glob strings; drop: tuple; rename/cast/defaults: OrderedDict;
# defaults values are typed raw values (see _typed); required: tuple


# ---------------------------------------------------------------------------
# The configuration document


def load_config(path, defaults):
    """Read and validate the ingest config; returns SourceSpecs in config order."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise InputError("cannot read ingest config %r: %s" % (path, exc.strerror or exc))
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ConfigError("ingest config %r is not valid UTF-8" % path)
    document = _parse_document(text, path)
    if isinstance(document, dict):
        if "sources" not in document:
            raise ConfigError("ingest config has no 'sources' list")
        entries = document["sources"]
    else:
        entries = document
    if not isinstance(entries, list) or not entries:
        raise ConfigError("ingest config 'sources' must be a non-empty list")
    base_dir = os.path.dirname(os.path.abspath(path))
    specs = []
    names = set()
    for index, entry in enumerate(entries):
        spec = _parse_source(index, entry, defaults, base_dir)
        if spec.name in names:
            raise ConfigError("source name %r is defined more than once" % spec.name)
        names.add(spec.name)
        specs.append(spec)
    return specs


def _parse_document(text, path):
    if path.lower().endswith(".json"):
        try:
            return json.loads(text)
        except ValueError as exc:
            raise ConfigError("malformed JSON ingest config: %s" % exc)
    try:
        import yaml
    except ImportError:  # pragma: no cover - PyYAML is a declared dependency
        try:
            return json.loads(text)
        except ValueError as exc:
            raise ConfigError("malformed ingest config (PyYAML unavailable): %s" % exc)
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError("malformed YAML ingest config: %s" % " ".join(str(exc).split()))


def _parse_source(index, entry, defaults, base_dir):
    if not isinstance(entry, dict):
        raise ConfigError("sources[%d] must be a mapping" % index)
    name = entry.get("name")
    if not isinstance(name, str) or not _SOURCE_NAME.match(name):
        raise ConfigError("sources[%d].name must be an identifier" % index)
    where = "source %r" % name

    patterns = entry.get("inputs")
    if isinstance(patterns, str):
        patterns = [patterns]
    if (not isinstance(patterns, list) or not patterns
            or not all(isinstance(p, str) and p.strip() for p in patterns)):
        raise ConfigError("%s: 'inputs' must be a non-empty list of paths or globs" % where)

    recursive = entry.get("recursive", defaults.recursive)
    if recursive is None:
        recursive = defaults.recursive
    if not isinstance(recursive, bool):
        raise ConfigError("%s: 'recursive' must be true or false" % where)

    fmt = entry.get("format")
    if fmt is None:
        fmt = defaults.format
    if not isinstance(fmt, str) or fmt.strip().lower() not in inputs.FORMATS:
        raise ConfigError("%s: 'format' must be one of %s" % (where, ", ".join(inputs.FORMATS)))
    fmt = fmt.strip().lower()

    schema = entry.get("schema")
    if schema is not None and (not isinstance(schema, str) or not _SOURCE_NAME.match(schema)):
        raise ConfigError("%s: 'schema' must be a schema name" % where)

    precedence = entry.get("precedence", 0)
    if precedence is None:
        precedence = 0
    if isinstance(precedence, float) and precedence.is_integer():
        precedence = int(precedence)
    if isinstance(precedence, bool) or not isinstance(precedence, int):
        raise ConfigError("%s: 'precedence' must be an integer" % where)

    tz = entry.get("tz")
    if tz is None:
        tz = defaults.tz
    ts_format = entry.get("timestamp_format", entry.get("timestamp-format"))
    if ts_format is None:
        ts_format = defaults.timestamp_format
    if not isinstance(tz, str) or not tz.strip():
        raise ConfigError("%s: 'tz' must be an IANA zone name" % where)
    if not isinstance(ts_format, (str, type(None))):
        raise ConfigError("%s: 'timestamp_format' must be a string" % where)
    try:
        ts_parser = TimestampParser(tz.strip(), ts_format)
    except MtlError as exc:
        raise ConfigError("%s: %s" % (where, exc))

    nulls = _nulls(entry.get("nulls"), defaults.nulls, where)

    mapping = entry.get("mapping")
    if mapping is None:
        mapping = {}
    if not isinstance(mapping, dict):
        raise ConfigError("%s: 'mapping' must be a mapping" % where)
    unknown = [k for k in mapping if k not in _MAPPING_KEYS]
    if unknown:
        raise ConfigError("%s: unknown mapping directive %r" % (where, unknown[0]))
    drop = tuple(_names(mapping.get("drop"), where, "mapping.drop"))
    rename = _str_map(mapping.get("rename"), where, "mapping.rename")
    targets = list(rename.values())
    for target in targets:
        if targets.count(target) > 1:
            raise ConfigError("%s: mapping.rename maps several columns to %r" % (where, target))
    cast = OrderedDict()
    for column, target in _str_map(mapping.get("cast"), where, "mapping.cast").items():
        lowered = target.strip().lower()
        if lowered not in TYPE_NAMES:
            raise ConfigError("%s: mapping.cast of %r to unknown type %r" % (where, column, target))
        cast[column] = lowered
    defaults_map = OrderedDict()
    raw_defaults = mapping.get("defaults")
    if raw_defaults is None:
        raw_defaults = {}
    if not isinstance(raw_defaults, dict):
        raise ConfigError("%s: mapping.defaults must be a mapping" % where)
    for column, value in raw_defaults.items():
        if not isinstance(column, str) or not column:
            raise ConfigError("%s: mapping.defaults keys must be column names" % where)
        typed = _typed(value, ts_parser)
        if typed is _INVALID:
            raise ConfigError("%s: mapping.defaults value for %r must be a scalar"
                              % (where, column))
        if typed is not None:
            defaults_map[column] = typed
    required = tuple(_names(entry.get("required"), where, "required"))

    return SourceSpec(name, tuple(p.strip() for p in patterns), recursive, fmt, schema,
                      precedence, ts_parser, nulls, drop, rename, cast, defaults_map, required,
                      base_dir)


def _nulls(value, fallback, where):
    if value is None:
        return fallback
    if isinstance(value, str):
        return frozenset(m.strip() for m in value.split(",") if m.strip() != "")
    if not isinstance(value, list):
        raise ConfigError("%s: 'nulls' must be a list of strings" % where)
    markers = set()
    for marker in value:
        if marker is None:  # an unquoted YAML null / ~
            markers.update(("null", "NULL", "Null", "~"))
        elif isinstance(marker, bool):
            markers.add("true" if marker else "false")
        elif isinstance(marker, (str, int, float)):
            markers.add(str(marker).strip())
        else:
            raise ConfigError("%s: 'nulls' must be a list of strings" % where)
    # "" is always null, as for --nulls; keep it out of the stripped marker set.
    return frozenset(m for m in markers if m != "")


def _names(value, where, what):
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError("%s: %s must be a list of column names" % (where, what))
    return value


def _str_map(value, where, what):
    if value is None:
        return OrderedDict()
    if not isinstance(value, dict):
        raise ConfigError("%s: %s must be a mapping" % (where, what))
    result = OrderedDict()
    for key, target in value.items():
        if not isinstance(key, str) or not key or not isinstance(target, str) or not target:
            raise ConfigError("%s: %s must map column names to names" % (where, what))
        result[key] = target
    return result


_INVALID = object()


def _typed(value, ts_parser):
    """A config scalar as a raw value (see _Raw), None for null, _INVALID otherwise."""
    if value is None:
        return None
    if isinstance(value, bool):
        return ("v", T.BOOL, value)
    if isinstance(value, int):
        return ("v", T.INT, value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return _INVALID
        return ("v", T.FLOAT, value)
    if isinstance(value, str):
        return ("t", value)
    if isinstance(value, datetime):
        return ("v", T.TIMESTAMP, ts_parser.localize(value))
    if isinstance(value, date):
        return ("v", T.TIMESTAMP, ts_parser.localize(datetime(value.year, value.month,
                                                              value.day)))
    return _INVALID


# ---------------------------------------------------------------------------
# File assignment


def assign_files(specs):
    """name -> files of that source (sorted by absolute path).

    A file matched by several sources goes to the one with the lowest
    precedence; equal lowest precedence is a configuration error.
    """
    matches = OrderedDict()   # realpath -> {source name: InputFile}
    for spec in specs:
        for pattern in spec.patterns:
            for key, entry in _expand(spec, pattern).items():
                matches.setdefault(key, OrderedDict()).setdefault(spec.name, entry)
    by_name = {spec.name: spec for spec in specs}
    assigned = OrderedDict((spec.name, []) for spec in specs)
    for key, claims in matches.items():
        best = min(by_name[n].precedence for n in claims)
        winners = [n for n in claims if by_name[n].precedence == best]
        if len(winners) > 1:
            raise ConfigError("file %r matches sources %s with equal precedence %d"
                              % (claims[winners[0]].path, ", ".join(repr(w) for w in winners),
                                 best))
        assigned[winners[0]].append(claims[winners[0]])
    for name in assigned:
        assigned[name].sort(key=lambda f: os.path.abspath(f.path))
    return assigned


def _expand(spec, pattern):
    """Files of one pattern; relative patterns are tried against the working
    directory first, then against the directory of the config file."""
    pattern = os.path.expanduser(pattern)
    candidates = [pattern]
    if not os.path.isabs(pattern):
        anchored = os.path.join(spec.base_dir, pattern)
        if os.path.abspath(pattern) != os.path.normpath(anchored):
            candidates.append(anchored)
    for candidate in candidates:
        if os.path.exists(candidate) or glob.has_magic(candidate):
            found = inputs.expand(candidate, spec.format, spec.recursive)
            if found:
                return found
    if not glob.has_magic(pattern) and not any(os.path.exists(c) for c in candidates):
        raise InputError("source %r: input %r does not exist" % (spec.name, pattern))
    return {}


# ---------------------------------------------------------------------------
# Typed rows of one source
#
# Raw values flowing through the mapping are tuples:
#   ("t", text)            a CSV/TSV cell
#   ("p", kind, value)     a Parquet value of logical `kind`
#   ("v", type, value)     an already typed value (after cast or from a default)


class SourceReader:
    """Static column types and (lazily) the typed rows of one configured source."""

    def __init__(self, spec, schemas, fallback_schema, files):
        self.spec = spec
        self.files = files
        self._rows = None
        self._mapped = None
        self.defaults = spec.defaults
        schema_name = spec.schema or fallback_schema
        if spec.schema is not None and spec.schema not in schemas:
            raise ConfigError("source %r uses schema %r, which the DSL does not define"
                              % (spec.name, spec.schema))
        self.schema = None if schema_name is None else resolve_named_schema(schemas,
                                                                            schema_name)
        if self.schema is not None:
            self.physical = OrderedDict(self.schema.physical)
            self._check_defaults()
            fields = self.schema.fields
            for name in spec.required:
                if name not in fields:
                    raise ConfigError("source %r: required field %r is not in schema %r"
                                      % (spec.name, name, self.schema.name))
            self.columns = OrderedDict((n, f.type) for n, f in fields.items())
            self._calcs = self._compile_calcs()
        else:
            self.physical = None      # inferred from the data on first use
            self.columns = None
            self._calcs = []

    # -- static -----------------------------------------------------------
    def _check_defaults(self):
        """Convert defaults of schema fields to the field types up front."""
        self.defaults = OrderedDict()
        for column, raw in self.spec.defaults.items():
            col_type = self.physical.get(column)
            if col_type is not None:
                if col_type == T.STRING and raw[0] == "v" and raw[1] != T.TIMESTAMP:
                    raw = ("t", _text_of(raw))
                try:
                    raw = ("v", col_type, _convert(raw, col_type, self._converter(column)))
                except S._CellError:
                    raise ConfigError("source %r: default for %r is not a valid %s"
                                      % (self.spec.name, column, col_type))
            self.defaults[column] = raw

    def _compile_calcs(self):
        names = _Types(self.physical)
        compiled = []
        for field in self.schema.calcs:
            result = compile_expression(field.expression, names, ts_parser=self.spec.ts_parser)
            if not is_assignable(field.type, result.type):
                raise TypeCheckError("schema field %r is declared %s but its expression is %s"
                                     % (field.name, field.type, result.type))
            names.define(field.name, field.type)
            compiled.append((field.name, coerce(field.type, result)))
        return compiled

    def _converter(self, column):
        return S._Converter(self.physical[column], self.spec.nulls, self.spec.ts_parser)

    def ensure_columns(self):
        """Column types; schema-less sources infer them from their files."""
        if self.columns is None:
            self._load()
        return self.columns

    # -- rows -------------------------------------------------------------
    def rows(self, log):
        """List of (provenance, values) of the rows that survived validation."""
        if self._rows is None:
            mapped = self._load()
            self._rows = self._convert_rows(mapped, log)
        return self._rows

    def _load(self):
        if self._mapped is None:
            mapped = []
            for entry in self.files:
                mapped.extend(self._read(entry))
            self._mapped = mapped
            if self.physical is None:
                self._infer(mapped)
        return self._mapped

    def _read(self, entry):
        table = S.read_file(entry)
        if table.kind == "parquet":
            table.load(set(table.columns), self.spec.ts_parser)
            columns = [(n,) + table.data[n] for n in table.columns if n in table.data]
            for index in range(table.nrows):
                prov = Q.Provenance(table.path, None, index + 1)
                raw = OrderedDict((n, ("p", kind, values[index])) for n, kind, values in columns)
                yield self._map(prov, raw)
            return
        header = table.columns
        width = len(header)
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
            yield self._map(prov, OrderedDict((h, ("t", c)) for h, c in zip(header, cells)))

    def _map(self, prov, raw):
        """Apply drop, rename, cast and defaults, in that order."""
        spec = self.spec
        for column in spec.drop:
            raw.pop(column, None)
        if spec.rename:
            renamed = OrderedDict()
            targets = {spec.rename[c] for c in raw if c in spec.rename}
            for column, value in raw.items():
                if column not in spec.rename and column not in targets:
                    renamed[column] = value
            for column, value in raw.items():
                if column in spec.rename:
                    renamed[spec.rename[column]] = value
            raw = renamed
        for column, target in spec.cast.items():
            if column not in raw:
                continue
            try:
                raw[column] = ("v", target, self._cast(raw[column], target))
            except S._CellError as err:
                return ("bad", Q.BadRecord(prov, err.classification,
                                           "column %r: cast to %s failed: %s"
                                           % (column, target, err.message),
                                           {"column": column, "value": _show(raw[column]),
                                            "cast": target}))
        for column, value in self.defaults.items():
            if column not in raw or self._is_null(raw[column]):
                raw[column] = value
        return ("row", prov, raw)

    def _is_null(self, raw):
        if raw[0] == "t":
            return raw[1] == "" or raw[1].strip() in self.spec.nulls
        value = raw[2]
        return value is None or (isinstance(value, float) and math.isnan(value))

    def _cast(self, raw, target):
        if self._is_null(raw):
            return None
        converter = S._Converter(target, self.spec.nulls, self.spec.ts_parser)
        if raw[0] == "t":
            return converter.text(raw[1])
        if raw[0] == "p":
            kind, value = raw[1], raw[2]
            if kind == "string":
                return converter.text(value)
            if kind == "binary":
                return converter.text(bytes(value).decode("utf-8", "replace"))
            if kind == "date":
                source = T.TIMESTAMP
                value = self.spec.ts_parser.localize(datetime(value.year, value.month,
                                                              value.day))
            elif kind == "decimal":
                source, value = T.FLOAT, float(value)
            elif kind in ("int", "float", "bool") or (kind == "timestamp"
                                                      and isinstance(value, datetime)):
                source = S._KIND_TYPES[kind]
            else:
                raise S._CellError(Q.PARQUET_TYPE_MISMATCH, "Parquet %s value %s cannot be "
                                   "cast to %s" % (kind, _show(raw), target))
        else:
            source, value = raw[1], raw[2]
        try:
            return cast_value(value, source, target, self.spec.ts_parser)
        except (TypeCheckError, ExecutionError, ValueError, OverflowError) as exc:
            raise S._CellError(Q.PARSE_TYPE_MISMATCH, "%s value %s cannot be cast to %s (%s)"
                               % (source, _show(raw), target, exc))

    def _infer(self, mapped):
        """Column types of a schema-less source (fixed event columns + inferred extras)."""
        seen = OrderedDict()
        for item in mapped:
            if item[0] == "row":
                for column, raw in item[2].items():
                    seen.setdefault(column, []).append(raw)
        types = OrderedDict(S.KNOWN)
        for column, raws in seen.items():
            if column in types:
                continue
            typed = {r[1] for r in raws if r[0] == "v" and r[2] is not None}
            kinds = {r[1] for r in raws if r[0] == "p" and r[2] is not None
                     and r[1] != "null"}
            cells = [r[1] for r in raws if r[0] == "t"]
            mapped_types = typed | {S._KIND_TYPES[k] for k in kinds}
            if not cells and mapped_types:
                if len(mapped_types) == 1:
                    types[column] = mapped_types.pop()
                    continue
                if mapped_types == {T.INT, T.FLOAT}:
                    types[column] = T.FLOAT
                    continue
            cells.extend(_text_of(r) for r in raws if r[0] != "t" and r[-1] is not None)
            types[column] = S._infer_text(cells, self.spec.nulls, self.spec.ts_parser)
        for column, target in self.spec.cast.items():
            if column in types:
                types[column] = target
        self.physical = types
        self.columns = OrderedDict(types)

    def _convert_rows(self, mapped, log):
        rows = []
        physical = self.physical
        converters = {n: self._converter(n) for n in physical}
        required = self.spec.required
        for item in mapped:
            if item[0] == "bad":
                log.add(item[1])
                continue
            prov, raw = item[1], item[2]
            values = OrderedDict()
            failure = None
            for name, col_type in physical.items():
                value = raw.get(name)
                try:
                    values[name] = None if value is None else _convert(value, col_type,
                                                                      converters[name])
                except S._CellError as err:
                    failure = Q.BadRecord(prov, err.classification,
                                          "column %r: %s" % (name, err.message),
                                          {"column": name, "value": _show(value),
                                           "expected_type": col_type})
                    break
            if failure is None:
                failure = self._missing(prov, values, required, physical)
            if failure is None:
                try:
                    for name, evaluate in self._calcs:
                        values[name] = evaluate(_Record(values))
                except (ExecutionError, TypeCheckError, ArithmeticError, ValueError) as exc:
                    failure = Q.BadRecord(prov, Q.RUNTIME_ERROR, str(exc), {"values": values})
            if failure is None:
                failure = self._missing(prov, values, required, None)
            if failure is not None:
                log.add(failure)
                continue
            rows.append((prov, values))
        return rows

    def _missing(self, prov, values, required, among):
        for name in required:
            if (among is None or name in among) and values.get(name) is None:
                return Q.BadRecord(prov, Q.MISSING_REQUIRED_FIELD,
                                   "required field %r is null" % name,
                                   {"column": name, "source": self.spec.name,
                                    "values": dict(values)})
        return None


def _convert(raw, col_type, converter):
    """Schema conversion of one mapped raw value; raises sources._CellError."""
    tag = raw[0]
    if tag == "t":
        return converter.text(raw[1])
    if tag == "p":
        return converter.parquet(raw[1], raw[2])
    value_type, value = raw[1], raw[2]
    if value is None:
        return None
    if value_type == col_type:
        return value
    if value_type == T.INT and col_type == T.FLOAT:
        return float(value)
    if value_type == T.STRING and col_type != T.STRING:
        return converter.text(value)
    raise S._CellError(Q.PARSE_TYPE_MISMATCH, "%s value %s does not conform to schema type %s"
                       % (value_type, _show(raw), col_type))


def _text_of(raw):
    if raw[0] == "p":
        return S._canonical_text(raw[1], raw[2])
    value = raw[2]
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        from .timestamps import format_utc
        return format_utc(value)
    return repr(value) if isinstance(value, float) else str(value)


def _show(raw):
    if raw is None:
        return None
    value = raw[-1]
    if isinstance(value, (datetime, date)):
        return str(value)
    return value


class _Types:
    def __init__(self, types):
        self._types = OrderedDict(types)

    def has(self, name):
        return name in self._types

    def type_of(self, name):
        return self._types[name]

    def define(self, name, value_type):
        self._types[name] = value_type


class _Record:
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data

    def get(self, name):
        return self.data.get(name)
