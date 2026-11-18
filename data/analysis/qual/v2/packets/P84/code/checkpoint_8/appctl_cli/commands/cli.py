"""``appctl cli``: information about appctl itself and its self-management."""

import json
import os
import platform
import pprint
import shutil

from .. import PROGRAM_NAME, __version__, container, database, upgrade
from ..arguments import is_assoc_token, parse_assoc_token
from ..config_loader import ALL_ALIAS, alias_sort_key, is_alias, packages_dir, root_dir
from ..errors import AppctlError
from ..extract import extract_archive, validate_archive
from ..file_cache import cache_dir
from ..formatter import format_value, to_json, to_yaml
from ..process import exec_command, run_command
from ..resolver import try_resolve
from ..runtime_config import GLOBAL_PARAMETERS, visible_parameters
from ..self_update import (UPDATE_ALL_FIELDS, UPDATE_FIELDS, available_updates,
                           selected_update_type, self_update, up_to_date_message)
from ..synopsis import ASSOC, FLAG, POSITIONAL
from ..system import (INSTALL_DIR, PRODUCT_NAME, archive_path, binary_path, ensure_requirements,
                      runtime_binary, runtime_binary_path, runtime_version)
from ._listing import LIST_OPTIONS, render_list

INFO_FORMATS = ("list", "json")
CHECK_UPDATE_FORMATS = ("table", "csv", "json", "count", "yaml")
PARAM_DUMP_FORMATS = ("json", "var_export")
ALIAS_FORMATS = ("yaml", "json")
SHELLS = ("bash", "zsh")

ALL_ALIAS_DESCRIPTION = "Run command against every registered alias."
FILE_MARKER = "<file> "
FILE_DESCRIPTION = "Path to a file."
UNINSTALL_QUESTION = (f"Are you sure you want to remove {PRODUCT_NAME} and all its projects "
                      "(along with their data)? This is an irreversible action. "
                      "No backup will be kept.")


def _environ(ctx):
    return ctx.environ if ctx.environ is not None else os.environ


def _check_format(fmt, allowed):
    if fmt not in allowed:
        raise AppctlError(f"Invalid format: {fmt}. Supported formats: {', '.join(allowed)}.")


# -- version / info ----------------------------------------------------------------


def version(ctx, args, assoc):
    ctx.output.line(__version__)


def _os_description():
    parts = (platform.system(), platform.release(), platform.version(), platform.machine())
    return " ".join(part for part in parts if part)


def info_data(ctx):
    environ = _environ(ctx)
    packages = packages_dir(environ)
    packages = packages if os.path.isdir(packages) else None
    config = ctx.config
    try:
        stored = upgrade.stored_version(database.get_db(environ))
    except AppctlError:
        stored = None
    return {
        "os": _os_description(),
        "shell": environ.get("SHELL") or environ.get("COMSPEC"),
        "runtime_binary": runtime_binary(environ),
        "runtime_binary_path": runtime_binary_path(environ),
        "runtime_version": runtime_version(environ),
        "python_version": platform.python_version(),
        "appctl_dir_path": INSTALL_DIR,
        "appctl_binary_path": binary_path(),
        "appctl_archive_path": archive_path(),
        "appctl_root_dir": root_dir(environ),
        "appctl_packages_dir_path": packages,
        "packages_dir": packages,
        "appctl_cache_dir": cache_dir(environ),
        "global_config_path": config.global_path if config else None,
        "project_config_path": config.project_path if config else None,
        "appctl_version": __version__,
        "appctl_stored_version": stored,
        "appctl_nightly": upgrade.is_nightly(),
        "release_channel": ctx.runtime.get("installer_version"),
        "strict_args_mode": ctx.strict,
        "runtime_config": {k: v for k, v in ctx.runtime.items()
                           if k in GLOBAL_PARAMETERS and v != GLOBAL_PARAMETERS[k].default},
    }


INFO_LABELS = (
    ("os", "OS"),
    ("shell", "Shell"),
    ("runtime_binary", "Runtime binary"),
    ("runtime_binary_path", "Runtime binary path"),
    ("runtime_version", "Runtime version"),
    ("appctl_dir_path", f"{PRODUCT_NAME} dir path"),
    ("appctl_binary_path", f"{PRODUCT_NAME} binary path"),
    ("appctl_archive_path", f"{PRODUCT_NAME} archive path"),
    ("appctl_root_dir", f"{PRODUCT_NAME} root dir"),
    ("appctl_packages_dir_path", f"{PRODUCT_NAME} packages dir"),
    ("appctl_cache_dir", f"{PRODUCT_NAME} cache dir"),
    ("global_config_path", f"{PRODUCT_NAME} global config"),
    ("project_config_path", f"{PRODUCT_NAME} project config"),
    ("appctl_version", f"{PRODUCT_NAME} version"),
    ("appctl_stored_version", f"{PRODUCT_NAME} stored version"),
    ("appctl_nightly", f"{PRODUCT_NAME} nightly build"),
    ("release_channel", f"{PRODUCT_NAME} release channel"),
    ("strict_args_mode", "Strict args mode"),
)


def _info_text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return format_value(value)


def info(ctx, args, assoc):
    fmt = assoc.get("format", "list")
    _check_format(fmt, INFO_FORMATS)
    data = info_data(ctx)
    if fmt == "json":
        ctx.output.line(json.dumps(data, indent=4, default=str))
        return
    for key, label in INFO_LABELS:
        value = data[key]
        if key == "strict_args_mode":
            value = "enabled" if value else "disabled"
        ctx.output.line(f"{label}:\t{_info_text(value)}")
    for key, value in data["runtime_config"].items():
        ctx.output.line(f"--{key}:\t{format_value(value)}")


# -- updates ----------------------------------------------------------------------------


def extract(ctx, assoc):
    """``cli update --archive``: extract a local ``.zip``/``.tar.gz`` into a directory."""
    archive = assoc.get("archive")
    validate_archive(archive)
    dest = assoc.get("path") or ctx.runtime.get("path") or os.getcwd()
    if dest is True:
        raise AppctlError("--path parameter needs a value.")
    dest = extract_archive(archive, str(dest), ctx.output)
    ctx.output.success(f"Extracted '{archive}' to '{dest}'.")


def update(ctx, args, assoc):
    if "archive" in assoc:
        return extract(ctx, assoc)
    return self_update(_environ(ctx), ctx.output, assoc, ctx.argv)


def check_update(ctx, args, assoc):
    fmt = assoc.get("format") or "table"
    _check_format(fmt, CHECK_UPDATE_FORMATS)
    only = selected_update_type(ctx.argv, assoc)
    updates = available_updates(_environ(ctx), __version__, only)
    if not updates and fmt == "table":
        ctx.output.success(up_to_date_message(only))
        return
    render_list(ctx, updates, dict(assoc, format=fmt), UPDATE_FIELDS, UPDATE_ALL_FIELDS,
                id_field="version", single_as_item=False)


def migrate(ctx, args, assoc):
    upgrade.run_upgrade(ctx.environ, ctx.output)
    ctx.output.success(f"Upgraded to {PROGRAM_NAME} {__version__}.")


# -- dumps ------------------------------------------------------------------------------


def param_dump(ctx, args, assoc):
    fmt = assoc.get("format", "json")
    _check_format(fmt, PARAM_DUMP_FORMATS)
    parameters = visible_parameters()
    dump = {}
    for name in sorted(parameters):
        param = parameters[name]
        entry = {
            "runtime": param.runtime,
            "file": param.file,
            "synopsis": param.synopsis,
            "default": param.default,
            "multiple": param.multiple,
            "description": param.description,
            "deprecated": param.deprecated,
        }
        if assoc.get("with-values"):
            entry["current"] = ctx.runtime.get(name)
        dump[name] = entry
    if fmt == "var_export":
        ctx.output.line(pprint.pformat(dump, sort_dicts=False))
    else:
        ctx.output.line(json.dumps(dump, indent=4, default=str))


def command_to_dict(command):
    entry = {
        "name": command.name,
        "description": command.description,
        "longdesc": command.longdesc or "",
        "subcommands": [command_to_dict(sub) for sub in command.sorted_subcommands()],
    }
    if not entry["subcommands"]:
        entry["synopsis"] = command.synopsis
    return entry


def cmd_dump(ctx, args, assoc):
    ctx.output.line(to_json(command_to_dict(ctx.root)))


def has_command(ctx, args, assoc):
    tokens = " ".join(str(arg) for arg in args).split()
    if not tokens:
        return 1
    resolved = try_resolve(ctx.root, tokens)
    if resolved is None or resolved[1]:
        return 1
    disabled = {" ".join(str(entry).split()) for entry in ctx.runtime.get("disabled_commands", ())}
    path = resolved[0].path
    if any(" ".join(path[:depth]) in disabled for depth in range(1, len(path) + 1)):
        return 1
    return 0


# -- aliases ----------------------------------------------------------------------------


def alias_listing(aliases):
    """Registered aliases by name; ``@all`` first when registered."""
    listing = {}
    if ALL_ALIAS in aliases:
        definition = aliases[ALL_ALIAS]
        listing[ALL_ALIAS] = ALL_ALIAS_DESCRIPTION if definition is None else definition
    for name in sorted((n for n in aliases if n != ALL_ALIAS), key=alias_sort_key):
        listing[name] = aliases[name]
    return listing


def alias(ctx, args, assoc):
    fmt = assoc.get("format", "yaml")
    _check_format(fmt, ALIAS_FORMATS)
    listing = alias_listing(ctx.config.aliases if ctx.config else {})
    ctx.output.line(to_json(listing) if fmt == "json" else to_yaml(listing))


# -- self-uninstall ----------------------------------------------------------------------

RESOURCES = (
    ("containers", ["ps", "-aq"], ["rm", "-f"]),
    ("networks", ["network", "ls", "-q"], ["network", "rm"]),
    ("volumes", ["volume", "ls", "-q"], ["volume", "rm", "-f"]),
    ("images", ["images", "-q"], ["rmi", "-f"]),
)


def _labeled_ids(list_command, output):
    argv = [container.RUNTIME_BINARY] + list_command + ["--filter",
                                                        f"label={container.VENDOR_LABEL}"]
    result = run_command(argv, output)
    if not result.succeeded:
        return None
    ids = []
    for item in result.stdout.split():
        if item not in ids:
            ids.append(item)
    return ids


def remove_runtime_resources(output):
    """Remove every appctl-labeled container, network, volume and image."""
    for kind, list_command, remove_command in RESOURCES:
        ids = _labeled_ids(list_command, output)
        if ids is None:
            output.warning(f"Unable to list the {PRODUCT_NAME} {kind}.")
            continue
        if ids and not exec_command([container.RUNTIME_BINARY] + remove_command + ids, output):
            output.warning(f"Unable to remove some {PRODUCT_NAME} {kind}.")


def _is_protected(path):
    path = os.path.realpath(path)
    protected = {os.path.realpath(os.sep), os.path.realpath(os.path.expanduser("~"))}
    return path in protected


def _remove_tree(path, output):
    if not path or not os.path.lexists(path):
        return
    if _is_protected(path):
        output.warning(f"Refusing to remove '{path}'.")
        return
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.unlink(path)
    except OSError as exc:
        output.warning(f"Unable to remove '{path}': {exc.strerror or exc}.")


def self_uninstall(ctx, args, assoc):
    environ = _environ(ctx)
    output = ctx.output
    ensure_requirements(environ, output)
    if not output.confirm(UNINSTALL_QUESTION, assoc):
        return 0
    remove_runtime_resources(output)
    try:
        projects = database.get_db(environ).get_projects()
    except AppctlError as exc:
        output.warning(f"Unable to read the projects: {exc.message}")
        projects = []
    database.close_all()
    for project in projects:
        _remove_tree(project["path"], output)
    if output.logger is not None:
        output.logger.enabled = False
    _remove_tree(root_dir(environ), output)
    archive = archive_path()
    if archive:
        _remove_tree(archive, output)
    output.success(f"{PRODUCT_NAME} has been removed successfully.")
    return 0


# -- tab completion -------------------------------------------------------------------------


def _completion_words(line):
    """Split the line into completed words and the word being typed."""
    words = line.split()
    current = words.pop() if words and not line[-1].isspace() else ""
    if words and os.path.basename(words[0]) in (PROGRAM_NAME, f"{PROGRAM_NAME}.py"):
        words = words[1:]
    elif not words and os.path.basename(current) in (PROGRAM_NAME, f"{PROGRAM_NAME}.py"):
        current = ""
    return words, current


def _alias_description(definition):
    if definition is None:
        return ALL_ALIAS_DESCRIPTION
    if isinstance(definition, list):
        return "Group of aliases: " + ", ".join(definition)
    if isinstance(definition, dict):
        target = definition.get("ssh") or definition.get("path") or definition.get("url")
        if target:
            return f"Alias for {target}."
    return "Alias."


def _is_file_positional(token):
    name = (token.name or "").lower()
    return name == "file" or name.endswith(("-file", "_file"))


def completion_suggestions(root, line, aliases=None):
    """``[(suggestion, description)]`` for the word at the end of ``line``, sorted."""
    words, current = _completion_words(line)
    alias_given = bool(words) and is_alias(words[0])
    if alias_given:
        words = words[1:]
    used = {parse_assoc_token(w)[0] for w in words if is_assoc_token(w)}
    command = root
    consumed = True
    positional_count = 0
    for word in (w for w in words if not is_assoc_token(w)):
        child = command.find_subcommand(word) if consumed else None
        if child is None:
            if not command.is_runnable or command.is_root:
                return []
            consumed = False
            positional_count += 1
            continue
        command = child

    found = {}

    def add(text, description=""):
        if text.startswith(current):
            found.setdefault(text, description or "")

    if consumed and command.is_root and not alias_given:
        for name, definition in (aliases or {}).items():
            add(f"{name} ", _alias_description(definition))
    if consumed:
        for sub in command.sorted_subcommands():
            add(f"{sub.name} ", sub.description)
    if command.is_runnable and not command.is_root:
        positionals = command.tokens_of_type(POSITIONAL)
        upcoming = None
        if positional_count < len(positionals):
            upcoming = positionals[positional_count]
        elif positionals and positionals[-1].repeating:
            upcoming = positionals[-1]
        if upcoming is not None and _is_file_positional(upcoming) and not current.startswith("-"):
            return [(FILE_MARKER, FILE_DESCRIPTION)]
        for token in command.tokens_of_type(ASSOC, FLAG):
            if token.name not in used:
                text = f"--{token.name}=" if token.type == ASSOC else f"--{token.name} "
                add(text, command.options.get(token.name, ""))
        for name, param in visible_parameters().items():
            if param.runtime and name not in used:
                add(f"--{name}=" if "=" in param.synopsis else f"--{name} ", param.description)
    return sorted(found.items(), key=lambda item: (item[0].lower(), item[0]))


def render_completion(suggestion, description, shell="bash"):
    if shell != "zsh":
        return suggestion
    name = suggestion.rstrip().replace("\\", "\\\\").replace(":", "\\:")
    summary = " ".join(str(description or "").split())
    return f"{name}:{summary}" if summary else name


def completions(ctx, args, assoc):
    shell = assoc.get("shell") or "bash"
    if shell not in SHELLS:
        raise AppctlError(f"Invalid shell: {shell}. Supported shells: {', '.join(SHELLS)}.")
    line = str(assoc["line"])
    point = assoc.get("point")
    if point is not None and point is not True:
        try:
            line = line[:max(int(point), 0)]
        except ValueError:
            pass
    aliases = ctx.config.aliases if ctx.config else {}
    for suggestion, description in completion_suggestions(ctx.root, line, aliases):
        ctx.output.line(render_completion(suggestion, description, shell))


# -- registration ---------------------------------------------------------------------------


def register(registry):
    registry.add("cli", description=f"Reviews current {PROGRAM_NAME} info and manages "
                                    f"{PROGRAM_NAME} itself.")
    registry.add(
        "cli alias", alias,
        synopsis="[--format=<format>]",
        description="Lists the registered aliases.",
        defaults={"format": "yaml"},
        options={"format": "Render output in a particular format (yaml, json)."},
        alias="aliases", machine_output=True,
    )
    registry.add(
        "cli check-update", check_update,
        synopsis="[--patch] [--minor] [--major] [--field=<field>] [--fields=<fields>] "
                 "[--format=<format>]",
        description=f"Checks for {PROGRAM_NAME} updates via the releases API.",
        options=dict(LIST_OPTIONS,
                     patch="Only list patch updates.",
                     minor="Only list minor updates.",
                     major="Only list major updates.",
                     format="Render output in a particular format (table, csv, json, count, "
                            "yaml)."),
    )
    registry.add(
        "cli cmd-dump", cmd_dump,
        description="Dumps the list of installed commands, as JSON.",
        machine_output=True,
    )
    registry.add(
        "cli completions", completions,
        synopsis="--line=<line> [--point=<point>] [--shell=<shell>]",
        description="Generates tab completion strings.",
        defaults={"shell": "bash"},
        options={"line": "The current command line to be executed.",
                 "point": "The index to the current cursor position relative to the beginning "
                          "of the command.",
                 "shell": "The shell to generate completions for (bash, zsh)."},
        machine_output=True,
    )
    registry.add(
        "cli has-command", has_command,
        synopsis="<command-name>...",
        description="Detects if a command exists.",
        options={"command-name": "The command to check."},
        machine_output=True,
    )
    registry.add(
        "cli info", info,
        synopsis="[--format=<format>]",
        description=f"Prints various details about the {PROGRAM_NAME} environment.",
        defaults={"format": "list"},
        options={"format": "Render output in a particular format (list, json)."},
    )
    registry.add(
        "cli migrate", migrate,
        description="Runs pending migrations and upgrades containers to the current version.",
    )
    registry.add(
        "cli param-dump", param_dump,
        synopsis="[--with-values] [--format=<format>]",
        description="Dumps the list of global parameters, as JSON or in var_export format.",
        defaults={"format": "json"},
        options={"with-values": "Display current values also.",
                 "format": "Render output in a particular format (json, var_export)."},
        machine_output=True,
    )
    registry.add(
        "cli self-uninstall", self_uninstall,
        synopsis="[--yes]",
        description=f"Removes {PROGRAM_NAME} and everything it created from the system.",
        options={"yes": "Do not prompt for confirmation."},
    )
    registry.add(
        "cli update", update,
        synopsis="[--stable] [--nightly] [--patch] [--minor] [--major] [--yes] "
                 "[--archive=<archive-path>] [--path=<destination>]",
        description=f"Updates {PROGRAM_NAME} to the latest release.",
        longdesc=(f"Without --stable or --nightly, checks for a newer version and asks to "
                  "install it.\nWith --archive, extracts a local .zip or .tar.gz archive into "
                  "a directory instead."),
        options={"stable": "Update to the latest stable release.",
                 "nightly": "Update to the latest nightly build.",
                 "patch": "Only perform patch updates.",
                 "minor": "Only perform minor updates.",
                 "major": "Only perform major updates.",
                 "yes": "Do not prompt for confirmation.",
                 "archive": "Path to a local archive to extract instead of updating.",
                 "path": "Directory to extract the archive into. Defaults to the current "
                         "directory."},
    )
    registry.add("cli version", version, description=f"Prints the {PROGRAM_NAME} version.",
                 machine_output=True)
