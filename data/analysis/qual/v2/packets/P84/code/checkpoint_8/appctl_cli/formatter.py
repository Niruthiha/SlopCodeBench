"""Rendering of records as table, csv, json, yaml, count or ids."""

import csv
import io
import json

import yaml

from .errors import AppctlError

LIST_FORMATS = ("table", "csv", "json", "yaml", "count", "ids")
ITEM_FORMATS = ("table", "csv", "json", "yaml")
JSON_INDENT = 4


def _text(value):
    """Cell text; arrays and objects are serialized as JSON."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value)
    return str(value)


def to_json(value):
    return json.dumps(value, indent=JSON_INDENT)


def to_yaml(value):
    text = yaml.safe_dump(value, default_flow_style=False, sort_keys=False,
                          allow_unicode=True, explicit_start=True)
    return text.rstrip("\n")


def _check_format(fmt, allowed):
    if fmt not in allowed:
        raise AppctlError(f"Invalid format: {fmt}. Supported formats: {', '.join(allowed)}.")


def resolve_field(name, available, prefix=None):
    """Return the canonical field for ``name``.

    Exact matches win, then ``<prefix>_<name>``; both are also tried
    case-insensitively.
    """
    candidates = [name] + ([f"{prefix}_{name}"] if prefix else [])
    for candidate in candidates:
        if candidate in available:
            return candidate
    lowered = {}
    for field in available:
        lowered.setdefault(field.lower(), field)
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    raise AppctlError(f"Invalid field: {name}.")


def select_fields(requested, default_fields, available, prefix=None):
    """Resolve ``--fields`` (comma separated) against the known fields."""
    if not requested or requested is True:
        return list(default_fields)
    fields = [f.strip() for f in str(requested).split(",") if f.strip()]
    return [resolve_field(name, available, prefix) for name in fields]


def _table(headers, rows):
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(cell)) for w, cell in zip(widths, row)]
    border = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def render(cells):
        return "|" + "|".join(f" {c.ljust(w)} " for c, w in zip(cells, widths)) + "|"

    lines = [border, render(headers), border]
    lines += [render(row) for row in rows]
    lines.append(border)
    return "\n".join(lines)


def _csv(headers, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue().rstrip("\n")


def format_items(items, fields, fmt="table", id_field="id", single_as_item=True):
    """Render records; with ``single_as_item`` a lone record's table is laid out vertically."""
    _check_format(fmt, LIST_FORMATS)
    if fmt == "count":
        return str(len(items))
    if fmt == "ids":
        return " ".join(_text(item.get(id_field)) for item in items)
    records = [{f: item.get(f) for f in fields} for item in items]
    if fmt == "json":
        return to_json(records)
    if fmt == "yaml":
        return to_yaml(records)
    if fmt == "table" and len(items) == 1 and single_as_item:
        return format_item(items[0], fields, "table")
    rows = [[_text(record[f]) for f in fields] for record in records]
    if fmt == "csv":
        return _csv(fields, rows)
    return _table(fields, rows)


def format_item(item, fields, fmt="table"):
    """A single record, laid out vertically as field/value pairs."""
    _check_format(fmt, ITEM_FORMATS)
    if fmt == "json":
        return to_json({f: item.get(f) for f in fields})
    if fmt == "yaml":
        return to_yaml({f: item.get(f) for f in fields})
    rows = [[f, _text(item.get(f))] for f in fields]
    if fmt == "csv":
        return _csv(["Field", "Value"], rows)
    return _table(["Field", "Value"], rows)


def format_value(value, fmt="plaintext"):
    if fmt == "json":
        return to_json(value)
    if fmt == "plaintext":
        return _text(value)
    raise AppctlError(f"Invalid format: {fmt}. Supported formats: plaintext, json.")
