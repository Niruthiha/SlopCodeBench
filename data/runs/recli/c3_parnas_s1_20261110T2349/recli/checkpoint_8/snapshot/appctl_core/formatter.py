"""Record rendering.

Secret: how a list of records is rendered in each supported output format,
how requested field names are matched against record keys (case-insensitive,
with an optional prefix), and when a single record is shown vertically.
"""

import csv
import io
import json

from . import messages as _messages
from . import yaml_lite
from .errors import CliError

_FORMATS = ("table", "json", "csv", "yaml", "ids", "count")


def supported_formats():
    return list(_FORMATS)


def _cell(value):
    """Scalar text for table and CSV cells; arrays and objects become JSON."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value)
    return str(value)


def _table_rows(header, rows):
    widths = [max([len(h)] + [len(row[i]) for row in rows])
              for i, h in enumerate(header)]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip()
                     for row in [header] + rows)


def _table(records, fields):
    return _table_rows(list(fields),
                       [[_cell(r.get(f)) for f in fields] for r in records])


def _vertical(record, fields):
    """One record laid out as Field/Value pairs."""
    return _table_rows(["Field", "Value"], [[f, _cell(record.get(f))] for f in fields])


def _csv(records, fields):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(fields)
    for record in records:
        writer.writerow([_cell(record.get(f)) for f in fields])
    return buffer.getvalue().rstrip("\n")


def _restrict(records, fields):
    return [{f: r.get(f) for f in fields} for r in records]


def _id_field(fields, available, prefix):
    for name in list(fields) + list(available):
        if name.casefold() == "id" or (prefix and name.casefold() == f"{prefix}_id".casefold()):
            return name
    return fields[0] if fields else None


def render(records, fields, fmt, prefix=None, vertical_single=True):
    """Render ``records`` (dicts) restricted to ``fields`` in format ``fmt``.

    Raises ``ValueError`` for an unsupported format.
    """
    fields = list(fields)
    records = list(records)
    if fmt == "table":
        if len(records) == 1 and vertical_single:
            return _vertical(records[0], fields)
        return _table(records, fields)
    if fmt == "json":
        return json.dumps(_restrict(records, fields), indent=4)
    if fmt == "csv":
        return _csv(records, fields)
    if fmt == "yaml":
        return yaml_lite.dump_records(_restrict(records, fields))
    if fmt == "ids":
        key = _id_field(fields, [k for r in records for k in r], prefix)
        return " ".join(_cell(r.get(key)) for r in records)
    if fmt == "count":
        return str(len(records))
    raise ValueError(fmt)


def render_field(records, field, fmt):
    """Only the values of ``field``, one per line."""
    if fmt == "json":
        return "\n".join(json.dumps(r.get(field)) for r in records)
    if fmt == "count":
        return str(len(records))
    return "\n".join(_cell(r.get(field)) for r in records)


class Formatter:
    """Resolves ``--format``, ``--field`` and ``--fields`` for a command."""

    def __init__(self, fmt="table", field=None, fields=None, prefix=None,
                 default_fields=(), formats=_FORMATS, vertical_single=True):
        self.format = fmt or "table"
        self.formats = list(formats)
        self.vertical_single = vertical_single
        self.field = field
        self.fields = fields
        self.prefix = prefix
        self.default_fields = list(default_fields)

    def _available(self, records):
        names = list(self.default_fields)
        for record in records:
            names.extend(record)
        return list(dict.fromkeys(names))

    def find_field(self, name, available):
        """Match ``name`` exactly, then case-insensitively, then with the
        prefix prepended. Raises ``CliError`` when nothing matches."""
        candidates = [name]
        if self.prefix and not name.casefold().startswith(f"{self.prefix}_".casefold()):
            candidates.append(f"{self.prefix}_{name}")
        for candidate in candidates:
            if candidate in available:
                return candidate
            folded = candidate.casefold()
            for key in available:
                if key.casefold() == folded:
                    return key
        raise CliError(_messages.invalid_field(name))

    def display(self, records):
        """Return the rendered text for ``records``."""
        records = list(records)
        if self.format not in self.formats:
            raise CliError(_messages.invalid_format(self.format, self.formats))
        available = self._available(records)
        if self.field:
            field = self.find_field(str(self.field), available)
            return render_field(records, field, self.format)
        if self.fields:
            requested = [f.strip() for f in str(self.fields).split(",") if f.strip()]
            fields = list(dict.fromkeys(self.find_field(f, available) for f in requested))
        else:
            fields = self.default_fields or available
        try:
            return render(records, fields, self.format, self.prefix, self.vertical_single)
        except ValueError:
            raise CliError(_messages.invalid_format(self.format, self.formats))


_MAPPING_FORMATS = ("list", "json", "yaml")


def supported_mapping_formats():
    return list(_MAPPING_FORMATS)


def render_mapping(mapping, fmt):
    """Render a single key/value mapping. Raises ``ValueError`` for an
    unsupported format."""
    if fmt == "list":
        width = max((len(k) for k in mapping), default=0)
        return "\n".join(f"{k.ljust(width)}  {v}" for k, v in mapping.items())
    if fmt == "json":
        return json.dumps(mapping)
    if fmt == "yaml":
        return "\n".join(["---"] + [f"{k}: {json.dumps(v)}" for k, v in mapping.items()])
    raise ValueError(fmt)


def _php_string(text):
    return "'" + str(text).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _php_value(value, indent):
    if value is None:
        return "NULL"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple, dict)):
        items = value.items() if isinstance(value, dict) else enumerate(value)
        pad = " " * indent
        lines = ["array ("]
        for key, item in items:
            key_text = repr(key) if isinstance(key, int) else _php_string(key)
            if isinstance(item, (list, tuple, dict)):
                lines.append(f"{pad}  {key_text} => ")
                lines.append(f"{pad}  {_php_value(item, indent + 2)},")
            else:
                lines.append(f"{pad}  {key_text} => {_php_value(item, indent + 2)},")
        lines.append(f"{pad})")
        return "\n".join(lines)
    return _php_string(value)


def var_export(value):
    """``value`` laid out like PHP's ``var_export``."""
    return _php_value(value, 0)
