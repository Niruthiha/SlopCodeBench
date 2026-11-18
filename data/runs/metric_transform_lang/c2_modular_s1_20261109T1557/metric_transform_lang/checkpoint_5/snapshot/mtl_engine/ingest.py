"""Declarative ingest config: named sources, file discovery/assignment and mapping rules."""
import glob
import json
import math
import os
from datetime import date, datetime, time, timezone

from . import dtypes, inputs
from .errors import ConfigError, IOFailure
from .loader import read_text
from .timeutil import TimestampParser, resolve_timezone

TYPE_NAMES = (dtypes.STRING, dtypes.INT, dtypes.FLOAT, dtypes.BOOL, dtypes.TIMESTAMP)
MAPPING_KEYS = ("rename", "cast", "defaults", "drop")
# Precedence of a source that does not declare one: lowest priority.
DEFAULT_PRECEDENCE = math.inf


class Mapping:
    """Per-source conversion: drop -> rename -> cast -> defaults (keys after rename)."""

    def __init__(self, rename, cast, defaults, drop):
        self.rename = rename
        self.cast = cast
        self.defaults = defaults  # raw config values until bound to a schema
        self.drop = drop


class SourceConfig:
    def __init__(self, name, patterns, recursive, file_format, schema, precedence, tz,
                 nulls, timestamp_format, mapping, required):
        self.name = name
        self.patterns = patterns
        self.recursive = recursive
        self.format = file_format
        self.schema = schema
        self.precedence = precedence
        self.tz = tz
        self.nulls = nulls
        self.timestamp_format = timestamp_format
        self.mapping = mapping
        self.required = required
        # Filled in by bind_schemas().
        self.resolved = None
        self.default_values = {}
        self.required_fields = []


class IngestConfig:
    def __init__(self, path, sources):
        self.path = path
        self.base_dir = os.path.dirname(os.path.abspath(path))
        self.sources = sources  # name -> SourceConfig, in declaration order


# --------------------------------------------------------------------------- loading


def load_config(path, cli_recursive=False, cli_format=inputs.AUTO):
    """Read and validate an ingest config file (YAML or JSON)."""
    text = read_text(path)
    data = _parse(path, text)
    if isinstance(data, dict):
        if "sources" not in data:
            raise ConfigError(f"ingest config '{path}' has no 'sources' list")
        entries = data["sources"]
    else:
        entries = data
    if isinstance(entries, dict):
        # `sources: {name: {...}, ...}` form.
        named = []
        for name, spec in entries.items():
            if not isinstance(spec, dict):
                raise ConfigError(f"source '{name}' must be a mapping")
            if "name" in spec and spec["name"] != name:
                raise ConfigError(f"source '{name}' declares a different name '{spec['name']}'")
            named.append(dict(spec, name=name))
        entries = named
    if not isinstance(entries, list) or not entries:
        raise ConfigError("'sources' must be a non-empty list of source declarations")

    sources = {}
    for idx, spec in enumerate(entries):
        source = _parse_source(spec, idx, cli_recursive, cli_format)
        if source.name in sources:
            raise ConfigError(f"duplicate source name '{source.name}'")
        sources[source.name] = source
    return IngestConfig(path, sources)


def _parse(path, text):
    if not text.strip():
        raise ConfigError(f"ingest config '{path}' is empty")
    try:
        return json.loads(text)
    except ValueError as json_exc:
        if path.lower().endswith(".json"):
            raise ConfigError(f"malformed JSON in ingest config '{path}': {json_exc}")
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - dependency is in requirements.txt
        raise ConfigError(f"cannot parse YAML config '{path}': PyYAML is not installed") from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"malformed YAML in ingest config '{path}': {exc}") from exc


def _parse_source(spec, idx, cli_recursive, cli_format):
    where = f"sources[{idx}]"
    if not isinstance(spec, dict):
        raise ConfigError(f"{where} must be a mapping")
    name = spec.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{where}: 'name' must be a non-empty string")
    name = name.strip()
    where = f"source '{name}'"

    patterns = spec.get("inputs", spec.get("input"))
    if isinstance(patterns, str):
        patterns = [patterns]
    if (not isinstance(patterns, list) or not patterns
            or not all(isinstance(p, str) and p.strip() for p in patterns)):
        raise ConfigError(f"{where}: 'inputs' must be a non-empty list of path patterns")

    recursive = spec.get("recursive")
    if recursive is None:
        recursive = None if not cli_recursive else True
    elif not isinstance(recursive, bool):
        raise ConfigError(f"{where}: 'recursive' must be true or false")

    file_format = spec.get("format", cli_format)
    if file_format is None:
        file_format = inputs.AUTO
    if not isinstance(file_format, str) or file_format.lower() not in inputs.FORMATS:
        raise ConfigError(f"{where}: 'format' must be one of {', '.join(inputs.FORMATS)}")
    file_format = file_format.lower()

    schema = spec.get("schema")
    if schema is not None and (not isinstance(schema, str) or not schema.strip()):
        raise ConfigError(f"{where}: 'schema' must be a schema name")

    precedence = spec.get("precedence", DEFAULT_PRECEDENCE)
    if isinstance(precedence, bool) or not isinstance(precedence, (int, float)) or (
            isinstance(precedence, float) and not precedence.is_integer()
            and precedence != DEFAULT_PRECEDENCE):
        raise ConfigError(f"{where}: 'precedence' must be an integer")

    tz = spec.get("tz")
    if tz is not None:
        if not isinstance(tz, str):
            raise ConfigError(f"{where}: 'tz' must be an IANA timezone name")
        try:
            tz = resolve_timezone(tz)
        except ValueError as exc:
            raise ConfigError(f"{where}: {exc}") from exc

    nulls = spec.get("nulls")
    if nulls is not None:
        nulls = _parse_nulls(nulls, where)

    ts_format = spec.get("timestamp_format", spec.get("timestamp-format"))
    if ts_format is not None and not isinstance(ts_format, str):
        raise ConfigError(f"{where}: 'timestamp_format' must be a string")

    mapping = _parse_mapping(spec.get("mapping"), where)

    required = spec.get("required", [])
    if required is None:
        required = []
    if isinstance(required, str):
        required = [required]
    if not isinstance(required, list) or not all(isinstance(r, str) for r in required):
        raise ConfigError(f"{where}: 'required' must be a list of field names")

    return SourceConfig(name, [p.strip() for p in patterns], recursive, file_format,
                        schema.strip() if schema else None, precedence, tz, nulls, ts_format,
                        mapping, required)


def _parse_nulls(value, where):
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        raise ConfigError(f"{where}: 'nulls' must be a list of strings")
    markers = {""}
    for item in value:
        if item is None:
            # An unquoted YAML null marker (null, NULL, ~).
            markers.update(("null", "NULL", "Null", "~"))
        elif isinstance(item, bool):
            raise ConfigError(f"{where}: 'nulls' entries must be strings")
        elif isinstance(item, (str, int, float)):
            markers.add(str(item).strip())
        else:
            raise ConfigError(f"{where}: 'nulls' entries must be strings")
    return frozenset(markers)


def _parse_mapping(spec, where):
    if spec is None:
        return Mapping({}, {}, {}, [])
    if not isinstance(spec, dict):
        raise ConfigError(f"{where}: 'mapping' must be a mapping")
    unknown = [k for k in spec if k not in MAPPING_KEYS]
    if unknown:
        raise ConfigError(f"{where}: unknown mapping directive(s): "
                          f"{', '.join(str(k) for k in unknown)}")

    rename = _string_map(spec.get("rename"), where, "rename")
    targets = {}
    for old, new in rename.items():
        if not isinstance(new, str) or not new.strip():
            raise ConfigError(f"{where}: rename target for '{old}' must be a column name")
        new = new.strip()
        if new in targets:
            raise ConfigError(f"{where}: columns '{targets[new]}' and '{old}' are both renamed "
                              f"to '{new}'")
        targets[new] = old
        rename[old] = new

    cast = _string_map(spec.get("cast"), where, "cast")
    for col, target in cast.items():
        if not isinstance(target, str) or target.strip().lower() not in TYPE_NAMES:
            raise ConfigError(f"{where}: cannot cast '{col}' to unknown type {target!r} "
                              f"(expected one of {', '.join(TYPE_NAMES)})")
        cast[col] = target.strip().lower()

    defaults = _string_map(spec.get("defaults"), where, "defaults")
    for col, value in defaults.items():
        if isinstance(value, (list, dict)):
            raise ConfigError(f"{where}: default for '{col}' must be a scalar value")

    drop = spec.get("drop", [])
    if drop is None:
        drop = []
    if isinstance(drop, str):
        drop = [drop]
    if not isinstance(drop, list) or not all(isinstance(d, str) for d in drop):
        raise ConfigError(f"{where}: 'drop' must be a list of column names")
    return Mapping(rename, cast, defaults, [d.strip() for d in drop])


def _string_map(value, where, key):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: mapping '{key}' must be a mapping of column names")
    result = {}
    for k, v in value.items():
        if not isinstance(k, str) or not k.strip():
            raise ConfigError(f"{where}: mapping '{key}' has an invalid column name {k!r}")
        result[k.strip()] = v
    return result


# --------------------------------------------------------------------------- schema binding


def bind_schemas(config, schemas, default_schema, ts_parser):
    """Resolve every source's schema; convert defaults and check required fields."""
    for source in config.sources.values():
        name = source.schema or default_schema
        if name not in schemas:
            raise ConfigError(f"source '{source.name}' references unknown schema '{name}'")
        source.schema = name
        resolved = schemas[name]
        source.resolved = resolved
        physical = resolved.physical
        mapping = source.mapping

        cast = {}
        for col, target in mapping.cast.items():
            cast[_mapped_name(col, mapping)] = target
        mapping.cast = cast

        parser = TimestampParser(source.tz or ts_parser.default_tz,
                                 source.timestamp_format or ts_parser.fmt)
        defaults = {}
        for col, value in mapping.defaults.items():
            col = _mapped_name(col, mapping)
            if col not in physical or value is None:
                continue
            defaults[col] = _convert_default(value, physical[col], source.name, col, parser)
        source.default_values = defaults

        required = []
        for col in source.required:
            col = _mapped_name(col.strip(), mapping)
            if col not in physical:
                raise ConfigError(f"source '{source.name}': required field '{col}' is not a "
                                  f"field of schema '{name}'")
            if col not in required:
                required.append(col)
        source.required_fields = required


def _mapped_name(col, mapping):
    """A cast/defaults/required key; a pre-rename column name is accepted too."""
    targets = set(mapping.rename.values())
    if col in mapping.rename and col not in targets:
        return mapping.rename[col]
    return col


def _convert_default(value, ftype, source, col, parser):
    def fail():
        raise ConfigError(f"source '{source}': default {value!r} for '{col}' is not a valid "
                          f"{ftype}")

    if ftype == dtypes.STRING:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)
    if ftype == dtypes.TIMESTAMP:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=parser.default_tz)
            return value.astimezone(timezone.utc)
        if isinstance(value, date):
            return datetime.combine(value, time()).replace(
                tzinfo=parser.default_tz).astimezone(timezone.utc)
        if isinstance(value, str):
            try:
                return parser.parse(value)
            except (ValueError, OverflowError):
                fail()
        fail()
    if ftype == dtypes.BOOL:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and dtypes.looks_like(value.strip(), dtypes.BOOL):
            return dtypes.parse_text(value.strip(), dtypes.BOOL)
        fail()
    if isinstance(value, bool):
        fail()
    if ftype == dtypes.INT:
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
    elif isinstance(value, (int, float)):
        if math.isfinite(value):
            return float(value)
        fail()
    if isinstance(value, str):
        try:
            return dtypes.parse_text(value.strip(), ftype)
        except ValueError:
            fail()
    fail()


# --------------------------------------------------------------------------- files


def assign_files(config, used):
    """Expand every source's patterns and assign each file to the matching source with
    the lowest precedence. Returns name -> [InputFile] sorted by absolute path for the
    `used` source names."""
    _check_pattern_overlap(config)
    claims = {}  # absolute path -> [(precedence, order, source name, display path)]
    for order, source in enumerate(config.sources.values()):
        seen = set()
        for pattern in source.patterns:
            matches = _expand(pattern, source, config.base_dir, source.name in used)
            for display in matches:
                key = os.path.realpath(display)
                if key in seen:
                    continue
                seen.add(key)
                claims.setdefault(key, []).append((source.precedence, order, source.name,
                                                   display))
        if source.name in used and not seen:
            raise IOFailure(f"source '{source.name}': no input files matched "
                            + ", ".join(source.patterns))

    assigned = {name: [] for name in used}
    for key, owners in claims.items():
        owners.sort(key=lambda o: (o[0], o[1]))
        best = owners[0]
        tied = [o for o in owners[1:] if o[0] == best[0]]
        if tied:
            names = ", ".join(f"'{o[2]}'" for o in [best] + tied)
            raise ConfigError(f"file '{best[3]}' matches sources {names} with equal "
                              f"precedence {_show_precedence(best[0])}")
        if best[2] in assigned:
            assigned[best[2]].append((key, best[3]))

    result = {}
    for name, files in assigned.items():
        source = config.sources[name]
        result[name] = [_input_file(display, source)
                        for _, display in sorted(files, key=lambda f: os.path.abspath(f[0]))]
    return result


def _show_precedence(value):
    return "(default)" if value == DEFAULT_PRECEDENCE else str(int(value))


def _check_pattern_overlap(config):
    """Identical patterns declared by sources of equal precedence can never be resolved."""
    owners = {}
    for source in config.sources.values():
        for pattern in source.patterns:
            key = (os.path.normpath(os.path.abspath(pattern)), source.precedence)
            other = owners.setdefault(key, source.name)
            if other != source.name:
                raise ConfigError(f"sources '{other}' and '{source.name}' declare the same "
                                  f"pattern '{pattern}' with equal precedence "
                                  f"{_show_precedence(source.precedence)}")


def _input_file(display, source):
    if source.format != inputs.AUTO:
        return inputs.InputFile(display, source.format)
    return inputs.InputFile(display, inputs.format_from_name(os.path.basename(display)))


def _expand(pattern, source, base_dir, must_exist):
    """Files matched by one pattern; relative patterns fall back to the config's directory."""
    expanded = os.path.expanduser(pattern)
    found = _expand_one(expanded, source)
    if found is None and not os.path.isabs(expanded):
        alt = os.path.join(base_dir, expanded)
        if os.path.normpath(alt) != os.path.normpath(os.path.abspath(expanded)):
            found = _expand_one(alt, source)
    if found is None:
        if must_exist and not glob.has_magic(expanded):
            raise IOFailure(f"source '{source.name}': input '{pattern}' does not exist")
        return []
    return found


def _expand_one(pattern, source):
    """Matches of `pattern`, or None when it matches nothing at all."""
    recursive = source.recursive
    if recursive is None:
        recursive = "**" in pattern
    if os.path.isdir(pattern):
        return [p for p in _scan(pattern, recursive) if _usable(p, source)]
    if os.path.isfile(pattern):
        return [pattern]
    if os.path.exists(pattern):
        raise IOFailure(f"source '{source.name}': input '{pattern}' is not a regular file")
    if not glob.has_magic(pattern):
        return None
    result = []
    for match in sorted(glob.glob(pattern, recursive=recursive)):
        if os.path.isdir(match):
            result.extend(p for p in _scan(match, recursive) if _usable(p, source))
        elif os.path.isfile(match) and _usable(match, source, explicit=True):
            result.append(match)
    return result or None


def _usable(path, source, explicit=False):
    name = os.path.basename(path)
    if name.startswith("."):
        return False
    if explicit and source.format != inputs.AUTO:
        return True
    return inputs.format_from_name(name) is not None or not inputs._has_extension(name)


def _scan(directory, recursive):
    return inputs._scan(directory, recursive)
