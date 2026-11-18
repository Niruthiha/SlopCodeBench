"""Shared helpers for commands that list or display records."""

from ..errors import AppctlError
from ..formatter import format_item, format_items, format_value, resolve_field, select_fields

RESERVED_KEYS = ("field", "fields", "format")

LIST_OPTIONS = {
    "field": "Prints the value of a single field for each item.",
    "fields": "Limit the output to specific object fields.",
    "format": "Render output in a particular format.",
}


def filter_items(items, assoc, available, prefix=None):
    """Keep items matching every generic ``--<field>=<value>`` filter."""
    filters = {}
    for key, value in assoc.items():
        if key in RESERVED_KEYS:
            continue
        try:
            filters[resolve_field(key, available, prefix)] = value
        except AppctlError:
            continue
    return [
        item for item in items
        if all(str(item.get(k)) == str(v) for k, v in filters.items())
    ]


def render_list(ctx, items, assoc, default_fields, available=None, id_field="id", prefix=None,
                single_as_item=True):
    available = list(available or default_fields)
    items = filter_items(items, assoc, available, prefix)
    fmt = assoc.get("format", "table")
    field = assoc.get("field")
    if field and field is not True:
        field = resolve_field(str(field).strip(), available, prefix)
        values = [item.get(field) for item in items]
        if fmt == "json":
            ctx.output.line(format_value(values, "json"))
        else:
            for value in values:
                ctx.output.line(format_value(value))
        return
    fields = select_fields(assoc.get("fields"), default_fields, available, prefix)
    ctx.output.line(format_items(items, fields, fmt, id_field=id_field,
                                 single_as_item=single_as_item))


def render_record(ctx, item, assoc, available, prefix=None):
    field = assoc.get("field")
    if field and field is not True:
        field = resolve_field(str(field).strip(), available, prefix)
        fmt = "json" if assoc.get("format") == "json" else "plaintext"
        ctx.output.line(format_value(item.get(field), fmt))
        return
    fields = select_fields(assoc.get("fields"), available, available, prefix)
    ctx.output.line(format_item(item, fields, assoc.get("format", "table")))


def confirm(ctx, assoc, question):
    """Prompt with ``[y/n]`` unless ``--yes``; False means the user cancelled."""
    return ctx.output.confirm(question, assoc)
