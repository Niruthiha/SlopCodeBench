"""Shared helpers for commands that list or display records."""

from ..errors import AppctlError
from ..formatter import format_item, format_items, format_value, select_fields

RESERVED_KEYS = ("field", "fields", "format")

LIST_OPTIONS = {
    "field": "Prints the value of a single field for each item.",
    "fields": "Limit the output to specific object fields.",
    "format": "Render output in a particular format.",
}


def filter_items(items, assoc, available):
    """Keep items matching every generic ``--<field>=<value>`` filter."""
    filters = {k: v for k, v in assoc.items() if k not in RESERVED_KEYS and k in available}
    return [
        item for item in items
        if all(str(item.get(k)) == str(v) for k, v in filters.items())
    ]


def render_list(ctx, items, assoc, default_fields, available=None, id_field="id"):
    available = list(available or default_fields)
    items = filter_items(items, assoc, available)
    fmt = assoc.get("format", "table")
    field = assoc.get("field")
    if field and field is not True:
        if field not in available:
            raise AppctlError(f"Invalid field: {field}.")
        values = [item.get(field) for item in items]
        if fmt == "json":
            ctx.output.line(format_value(values, "json"))
        else:
            for value in values:
                ctx.output.line(format_value(value))
        return
    fields = select_fields(assoc.get("fields"), default_fields, available)
    ctx.output.line(format_items(items, fields, fmt, id_field=id_field))


def render_record(ctx, item, assoc, available):
    field = assoc.get("field")
    if field and field is not True:
        if field not in available:
            raise AppctlError(f"Invalid field: {field}.")
        fmt = "json" if assoc.get("format") == "json" else "plaintext"
        ctx.output.line(format_value(item.get(field), fmt))
        return
    fields = select_fields(assoc.get("fields"), available, available)
    ctx.output.line(format_item(item, fields, assoc.get("format", "table")))


def require_confirmation(assoc, question):
    if not assoc.get("yes"):
        raise AppctlError(f"{question} Re-run with --yes to confirm.")
