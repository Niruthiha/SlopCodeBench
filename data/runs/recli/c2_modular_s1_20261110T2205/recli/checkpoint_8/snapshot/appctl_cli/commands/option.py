"""``appctl option``: retrieve and set options (simulated)."""

import fnmatch

from ..errors import AppctlError
from ..formatter import format_value
from ._listing import LIST_OPTIONS, render_list

OPTIONS = [
    {"option_name": "admin_email", "option_value": "admin@example.test", "autoload": "yes"},
    {"option_name": "blogname", "option_value": "My Application", "autoload": "yes"},
    {"option_name": "home", "option_value": "https://example.test", "autoload": "yes"},
    {"option_name": "siteurl", "option_value": "https://example.test", "autoload": "yes"},
    {"option_name": "timezone_string", "option_value": "UTC", "autoload": "no"},
]
FIELDS = ["option_name", "option_value", "autoload"]


def _find(key):
    return next((o for o in OPTIONS if o["option_name"] == key), None)


def add(ctx, args, assoc):
    key, value = args
    if _find(key):
        raise AppctlError(f"Could not add option '{key}'. Does it already exist?")
    ctx.output.success(f"Added '{key}' option (autoload: {assoc['autoload']}).")


def delete(ctx, args, assoc):
    for key in args:
        if _find(key):
            ctx.output.success(f"Deleted '{key}' option.")
        else:
            ctx.output.warning(f"Could not delete '{key}' option. Does it exist?")


def get(ctx, args, assoc):
    option = _find(args[0])
    if option is None:
        raise AppctlError(f"Could not get '{args[0]}' option. Does it exist?")
    ctx.output.line(format_value(option["option_value"], assoc["format"]))


def list_(ctx, args, assoc):
    items = OPTIONS
    pattern = assoc.get("search")
    if pattern and pattern is not True:
        items = [o for o in items if fnmatch.fnmatchcase(o["option_name"], pattern)]
    autoload = assoc.get("autoload")
    if autoload in ("on", "off", "yes", "no"):
        wanted = "yes" if autoload in ("on", "yes") else "no"
        items = [o for o in items if o["autoload"] == wanted]
    filters = {k: v for k, v in assoc.items() if k not in ("search", "autoload")}
    render_list(ctx, items, filters, ["option_name", "option_value"], FIELDS,
                id_field="option_name", prefix="option")


def update(ctx, args, assoc):
    key, value = args
    option = _find(key)
    if option and option["option_value"] == value:
        ctx.output.success(f"Value passed for '{key}' option is unchanged.")
    elif option:
        ctx.output.success(f"Updated '{key}' option.")
    else:
        ctx.output.success(f"Added '{key}' option.")


def register(registry):
    registry.add("option", description="Retrieves and sets options, including plugin and theme settings.")
    value_options = {
        "key": "The name of the option.",
        "value": "The value of the option.",
        "format": "The serialization format for the value (plaintext, json).",
        "autoload": "Should this option be automatically loaded (yes, no).",
    }
    registry.add(
        "option add", add,
        synopsis="<key> [<value>] [--format=<format>] [--autoload=<autoload>]",
        description="Adds a new option value.",
        defaults={"value": "", "format": "plaintext", "autoload": "yes"},
        options=value_options,
    )
    registry.add(
        "option delete", delete,
        synopsis="<key>...",
        description="Deletes an option.",
        options={"key": "Key for the option."},
    )
    registry.add(
        "option get", get,
        synopsis="<key> [--format=<format>]",
        description="Gets the value for an option.",
        defaults={"format": "plaintext"},
        options=value_options, machine_output=True,
    )
    registry.add(
        "option list", list_,
        synopsis="[--search=<pattern>] [--autoload=<value>] [--field=<field>] "
                 "[--fields=<fields>] [--format=<format>]",
        description="Lists options and their values.",
        defaults={"format": "table"},
        options=dict(LIST_OPTIONS, search="Use wildcards ( * and ? ) to match option name.",
                     autoload="Match only autoload options when value is on, and only "
                              "not-autoload options when off."),
    )
    registry.add(
        "option update", update,
        synopsis="<key> [<value>] [--autoload=<autoload>] [--format=<format>]",
        description="Updates an option value.",
        alias="set",
        defaults={"value": "", "format": "plaintext"},
        options=value_options,
    )
