"""``appctl config``: configuration file management (simulated)."""

import os

from ..errors import AppctlError
from ._listing import LIST_OPTIONS, render_list

CONFIG_FILE = "config.php"
TYPES = ("constant", "variable", "all")

ENTRIES = [
    {"name": "DB_NAME", "value": "appctl", "type": "constant"},
    {"name": "DB_USER", "value": "appctl", "type": "constant"},
    {"name": "DB_HOST", "value": "localhost", "type": "constant"},
    {"name": "DEBUG", "value": False, "type": "constant"},
    {"name": "table_prefix", "value": "app_", "type": "variable"},
]


def _check_type(entry_type):
    if entry_type not in TYPES:
        raise AppctlError(f"Invalid type '{entry_type}'. Expected one of: {', '.join(TYPES)}.")


def _find(name, entry_type):
    _check_type(entry_type)
    for entry in ENTRIES:
        if entry["name"] == name and entry_type in ("all", entry["type"]):
            return entry
    return None


def _label(entry_type):
    return "constant or variable" if entry_type == "all" else entry_type


def get(ctx, args, assoc):
    entry = _find(args[0], assoc["type"])
    if entry is None:
        raise AppctlError(
            f"The {_label(assoc['type'])} '{args[0]}' is not defined in the '{CONFIG_FILE}' file."
        )
    value = entry["value"]
    ctx.output.line(str(value).lower() if isinstance(value, bool) else str(value))


def set_(ctx, args, assoc):
    name, value = args
    entry = _find(name, assoc["type"])
    kind = entry["type"] if entry else ("constant" if assoc["type"] == "all" else assoc["type"])
    verb = "Updated" if entry else "Added"
    preposition = "in" if entry else "to"
    raw = " (raw)" if assoc.get("raw") else ""
    ctx.output.success(
        f"{verb} the {kind} '{name}' {preposition} the '{CONFIG_FILE}' file with the{raw} value '{value}'."
    )


def delete(ctx, args, assoc):
    entry = _find(args[0], assoc["type"])
    if entry is None:
        raise AppctlError(
            f"The {_label(assoc['type'])} '{args[0]}' is not defined in the '{CONFIG_FILE}' file."
        )
    ctx.output.success(f"Deleted the {entry['type']} '{args[0]}' from the '{CONFIG_FILE}' file.")


def list_(ctx, args, assoc):
    render_list(ctx, ENTRIES, assoc, ["name", "value", "type"], id_field="name")


def create(ctx, args, assoc):
    details = (
        f"database: {assoc['dbname']}, user: {assoc['dbuser']}, "
        f"host: {assoc['dbhost']}, prefix: {assoc['dbprefix']}, locale: {assoc['locale']}"
    )
    ctx.output.success(f"Generated '{CONFIG_FILE}' file ({details}).")


def path(ctx, args, assoc):
    base = ctx.runtime.get("path") or os.getcwd()
    ctx.output.line(os.path.join(str(base), CONFIG_FILE))


def register(registry):
    registry.add("config", description="Generates and reads the configuration file.", alias="cfg")
    type_option = {"type": "Type of config value to target (constant, variable, all)."}
    registry.add(
        "config create", create,
        synopsis="--dbname=<dbname> --dbuser=<dbuser> [--dbpass=<dbpass>] [--dbhost=<dbhost>] "
                 "[--dbprefix=<dbprefix>] [--locale=<locale>] [--force] [--skip-check]",
        description="Generates a configuration file.",
        defaults={"dbpass": "", "dbhost": "localhost", "dbprefix": "app_", "locale": "en_US"},
        options={"dbname": "Set the database name.", "dbuser": "Set the database user.",
                 "dbpass": "Set the database user password.", "dbhost": "Set the database host.",
                 "dbprefix": "Set the database table prefix.", "locale": "Set the locale.",
                 "force": "Overwrite existing configuration file.",
                 "skip-check": "Skip the database connection check."},
    )
    registry.add(
        "config delete", delete,
        synopsis="<name> [--type=<type>]",
        description="Deletes a specific constant or variable from the configuration file.",
        defaults={"type": "all"}, options=type_option,
    )
    registry.add(
        "config get", get,
        synopsis="<name> [--type=<type>]",
        description="Gets the value of a specific constant or variable defined in the configuration file.",
        defaults={"type": "all"}, options=type_option, machine_output=True,
    )
    registry.add(
        "config list", list_,
        synopsis="[--fields=<fields>] [--format=<format>]",
        description="Lists variables, constants, and file includes defined in the configuration file.",
        defaults={"format": "table"}, options=LIST_OPTIONS,
    )
    registry.add("config path", path, description="Gets the path to the configuration file.",
                 machine_output=True)
    registry.add(
        "config set", set_,
        synopsis="<name> <value> [--type=<type>] [--raw]",
        description="Sets the value of a specific constant or variable defined in the configuration file.",
        defaults={"type": "all"},
        options=dict(type_option, raw="Place the value into the file as is, instead of as a quoted string."),
    )
