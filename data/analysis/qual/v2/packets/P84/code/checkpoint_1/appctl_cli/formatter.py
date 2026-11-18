"""Rendering of records as table, csv, json, yaml, count or ids."""

import csv
import io
import json

from .errors import AppctlError

LIST_FORMATS = ("table", "csv", "json", "yaml", "count", "ids")
ITEM_FORMATS = ("table", "csv", "json", "yaml")


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _check_format(fmt, allowed):
    if fmt not in allowed:
        raise AppctlError(f"Invalid format: {fmt}. Supported formats: {', '.join(allowed)}.")


def select_fields(requested, default_fields, available):
    """Resolve ``--fields`` (comma separated) against the known fields."""
    if not requested or requested is True:
        return list(default_fields)
    fields = [f.strip() for f in str(requested).split(",") if f.strip()]
    for name in fields:
        if name not in available:
            raise AppctlError(f"Invalid field: {name}.")
    return fields


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


def _yaml_scalar(value):
    text = _text(value)
    if text == "" or any(ch in text for ch in ":#'\"{}[],&*!|>%@`") or text.strip() != text:
        return json.dumps(text)
    return text


def format_items(items, fields, fmt="table", id_field="id"):
    _check_format(fmt, LIST_FORMATS)
    if fmt == "count":
        return str(len(items))
    if fmt == "ids":
        return " ".join(_text(item.get(id_field)) for item in items)
    if fmt == "json":
        return json.dumps([{f: item.get(f) for f in fields} for item in items])
    if fmt == "yaml":
        if not items:
            return "--- []"
        lines = ["---"]
        for item in items:
            for index, name in enumerate(fields):
                prefix = "- " if index == 0 else "  "
                lines.append(f"{prefix}{name}: {_yaml_scalar(item.get(name))}")
        return "\n".join(lines)
    rows = [[_text(item.get(f)) for f in fields] for item in items]
    if fmt == "csv":
        return _csv(fields, rows)
    return _table(fields, rows)


def format_item(item, fields, fmt="table"):
    _check_format(fmt, ITEM_FORMATS)
    if fmt == "json":
        return json.dumps({f: item.get(f) for f in fields})
    if fmt == "yaml":
        return "\n".join(["---"] + [f"{f}: {_yaml_scalar(item.get(f))}" for f in fields])
    rows = [[f, _text(item.get(f))] for f in fields]
    if fmt == "csv":
        return _csv(["Field", "Value"], rows)
    return _table(["Field", "Value"], rows)


def format_value(value, fmt="plaintext"):
    if fmt == "json":
        return json.dumps(value)
    if fmt == "plaintext":
        return _text(value)
    raise AppctlError(f"Invalid format: {fmt}. Supported formats: plaintext, json.")
