"""The ``cli`` command family.

Secret: what each command reviewing or managing appctl itself does: which
diagnostics are reported and under which labels, how updates are filtered
and shown, how the self-update is confirmed and carried out, how the
parameter and command dumps are laid out, and which resources a
self-uninstall removes and in which order.
"""

import json
import os
import shutil
import sys

from . import (catalog, completions, config_spec, containers, extractor, formatter,
               messages, releases, semver, system, yaml_lite)
from .errors import CliError

_ROOT_NAME = "appctl"
_ROOT_DESCRIPTION = "Manages AppCtl projects, their containers and AppCtl itself."
_UPDATE_FIELDS = ["version", "update_type", "package_url"]
_UPDATE_FORMATS = ("table", "csv", "json", "count", "yaml")
_INFO_FORMATS = ("list", "json", "yaml")
_DUMP_FORMATS = ("json", "var_export")
_ALIAS_FORMATS = ("yaml", "json")
_LIST_FORMAT = "[--field=<field>] [--fields=<fields>] [--format=<format>]"


def _invalid_format(fmt, supported):
    return CliError(messages.invalid_format(fmt, supported))


# --- version and info -------------------------------------------------------------

def _cli_version(ctx):
    ctx.out.line(catalog.VERSION)
    return 0


def info_items(ctx):
    """``[(key, label, value)]`` describing the appctl environment."""
    config, env = ctx.config, ctx.env
    packages = config.packages_dir()
    stored = ctx.db.get_option("version") if ctx.db is not None else False
    return [
        ("os", "OS", system.os_description()),
        ("shell", "Shell", system.shell(env)),
        ("runtime_binary", "Python binary", system.runtime_binary(env)),
        ("runtime_version", "Python version", system.runtime_version()),
        ("runtime_prefix", "Python prefix", sys.prefix),
        ("appctl_dir", "AppCtl dir path", system.install_dir()),
        ("binary_path", "AppCtl binary path", system.binary_path(env)),
        ("archive_path", "AppCtl archive path", system.archive_path()),
        ("root_dir", "AppCtl root dir", config.root_dir()),
        ("packages_dir", "AppCtl packages dir",
         packages if packages and os.path.isdir(packages) else None),
        ("cache_dir", "AppCtl cache dir", ctx.cache.get_root() if ctx.cache else None),
        ("global_config_path", "AppCtl global config", config.global_config_path()),
        ("project_config_path", "AppCtl project config", config.project_config_path()),
        ("path", "Path", config.path()),
        ("url", "URL", config.url()),
        ("user", "User", config.user()),
        ("color", "Color", config.color()),
        ("debug", "Debug", config.debug()),
        ("quiet", "Quiet", config.quiet()),
        ("strict_args_mode", "Strict arguments mode", config.strict()),
        ("version", "AppCtl version", catalog.VERSION),
        ("stored_version", "AppCtl stored version", stored if stored is not False else None),
        ("release_channel", "AppCtl release channel",
         releases.NIGHTLY if releases.is_nightly(catalog.VERSION) else "stable"),
    ]


def _list_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _cli_info(ctx):
    fmt = ctx.args.option("format")
    items = info_items(ctx)
    if fmt == "list":
        ctx.out.line("\n".join(f"{label}:\t{_list_value(value)}"
                               for _, label, value in items))
        return 0
    if fmt not in _INFO_FORMATS:
        raise _invalid_format(fmt, _INFO_FORMATS)
    ctx.out.line(formatter.render_mapping({key: value for key, _, value in items}, fmt))
    return 0


# --- updates -----------------------------------------------------------------------

def update_filter(raw_options):
    """The last of ``--patch``, ``--minor`` and ``--major`` given."""
    chosen = None
    for name, value in raw_options:
        if name in releases.UPDATE_TYPES and value is None:
            chosen = name
    return chosen


def _cli_check_update(ctx):
    kind = update_filter(ctx.raw_options)
    fmt = ctx.args.option("format", "table")
    if fmt not in _UPDATE_FORMATS:
        raise _invalid_format(fmt, _UPDATE_FORMATS)
    updates = releases.available_updates(catalog.VERSION, ctx.env, kind)
    if not updates and fmt == "table":
        ctx.out.success(messages.at_latest_version(kind))
        return 0
    display = formatter.Formatter(fmt, field=ctx.args.option("field"),
                                  fields=ctx.args.option("fields"),
                                  default_fields=_UPDATE_FIELDS, formats=_UPDATE_FORMATS,
                                  vertical_single=False)
    ctx.out.line(display.display(updates))
    return 0


def self_update(out, env, yes=False, stable=False, nightly=False):
    """Download, validate and install a newer archive over the running
    binary. Returns the exit code."""
    if system.is_darwin():
        raise CliError(messages.self_update_unavailable())
    binary = system.binary_path(env)
    if not system.is_writable(binary):
        raise CliError(messages.binary_not_writable(binary))
    current = catalog.VERSION
    if nightly:
        label = None
        url = releases.nightly_url(env)
        question = messages.update_confirmation(current, "the latest nightly build")
    elif stable:
        latest = releases.latest_stable(env)
        label, url = None, latest["package_url"]
        question = messages.update_confirmation(
            current, f"the latest stable release ({latest['version']})")
    else:
        updates = releases.available_updates(current, env)
        if not updates:
            out.success(messages.at_latest_version())
            return 0
        newest = max(updates, key=lambda u: semver.parse(u["version"]) or semver.parse("0"))
        label, url = newest["version"], newest["package_url"]
        question = messages.update_confirmation(current, label)
    if not out.confirm(question, yes):
        return 0
    version = releases.install(url, binary, env, out)
    out.success(messages.update_completed(label or version))
    return 0


def _extract_archive(ctx):
    """Extract a local ``.zip`` or ``.tar.gz`` archive into ``--path`` (the
    current directory by default)."""
    archive = os.path.join(ctx.cwd, os.path.expanduser(ctx.args.option("archive")))
    extractor.validate(archive)
    destination = ctx.args.option("path") or ctx.config.path() or ctx.cwd
    destination = os.path.join(ctx.cwd, os.path.expanduser(str(destination)))
    extractor.extract(archive, destination, ctx.out)
    ctx.out.success(messages.archive_extracted(archive, destination))
    return 0


def _cli_update(ctx):
    args = ctx.args
    if args.option("archive"):
        return _extract_archive(ctx)
    return self_update(ctx.out, ctx.env, yes=bool(args.option("yes")),
                       stable=bool(args.option("stable")),
                       nightly=bool(args.option("nightly")))


def _cli_migrate(ctx):
    catalog.upgrader(ctx.db, ctx.out, ctx.env, ctx.config).run()
    ctx.out.success(messages.upgrade_completed())
    return 0


# --- dumps -------------------------------------------------------------------------

def _dump(ctx, data, formats):
    fmt = ctx.args.option("format")
    if fmt == "json":
        ctx.out.line(json.dumps(data))
    elif fmt == "var_export" and "var_export" in formats:
        ctx.out.line(formatter.var_export(data))
    elif fmt == "yaml" and "yaml" in formats:
        ctx.out.line("---\n" + yaml_lite.dump(data).rstrip("\n") if data else "--- {}")
    else:
        raise _invalid_format(fmt, formats)
    return 0


def _cli_param_dump(ctx):
    dump = {}
    for param in sorted(config_spec.visible(), key=lambda p: p.name):
        entry = {
            "runtime": param.runtime or False,
            "file": param.file,
            "default": param.default,
            "desc": param.description,
        }
        if param.deprecated:
            entry["deprecated"] = True
        if ctx.args.option("with-values"):
            entry["current"] = ctx.config.get(param.name)
        dump[param.name] = entry
    return _dump(ctx, dump, _DUMP_FORMATS)


def command_dump(node):
    """The command tree below ``node`` as nested mappings."""
    entry = {
        "name": node.name or _ROOT_NAME,
        "description": node.description or (_ROOT_DESCRIPTION if node.is_root() else ""),
        "longdesc": node.longdesc,
        "subcommands": [command_dump(child)
                        for child in sorted(node.children(), key=lambda c: c.path)],
    }
    if not node.has_children():
        entry["synopsis"] = node.synopsis.text()
    return entry


def _cli_cmd_dump(ctx):
    ctx.out.line(json.dumps(command_dump(ctx.tree.root)))
    return 0


def _cli_has_command(ctx):
    words = " ".join(ctx.args.positionals).split()
    node = ctx.tree.find(words)
    if node is None:
        return 1
    disabled = set(ctx.config.disabled_commands())
    path = node.path.split()
    if any(" ".join(path[:i]) in disabled for i in range(1, len(path) + 1)):
        return 1
    return 0


# --- aliases and completion ---------------------------------------------------------

def _alias_definitions(ctx):
    registry = ctx.config.aliases()
    return registry.definitions() if registry is not None else {}


def _cli_alias(ctx):
    fmt = ctx.args.option("format")
    if fmt not in _ALIAS_FORMATS:
        raise _invalid_format(fmt, _ALIAS_FORMATS)
    definitions = _alias_definitions(ctx)
    ordered = {name: definitions[name]
               for name in sorted(definitions, key=lambda n: (n.casefold(), n))}
    return _dump(ctx, ordered, _ALIAS_FORMATS)


def _cli_completions(ctx):
    line = ctx.args.option("line") or ""
    point = ctx.args.option("point")
    try:
        point = int(str(point).strip())
    except ValueError:
        raise CliError(messages.invalid_point(point)) from None
    shell = ctx.args.option("shell", "bash")
    if shell not in completions.SHELLS:
        raise CliError(messages.invalid_shell(shell, completions.SHELLS))
    point = max(0, min(point, len(line)))
    items = completions.suggestions(ctx.tree, line[:point], _alias_definitions(ctx))
    for text in completions.render(items, shell):
        ctx.out.line(text)
    return 0


# --- self-uninstall ------------------------------------------------------------------

_LABEL_FILTER = f"label={containers.VENDOR_LABEL}"
_RESOURCES = (
    ("containers", ["ps", "-aq", "--filter", _LABEL_FILTER], ["rm", "-f"]),
    ("networks", ["network", "ls", "-q", "--filter", _LABEL_FILTER], ["network", "rm"]),
    ("volumes", ["volume", "ls", "-q", "--filter", _LABEL_FILTER], ["volume", "rm", "-f"]),
    ("images", ["image", "ls", "-q", "--filter", _LABEL_FILTER], ["image", "rm", "-f"]),
)


def _failure(result):
    return result.stderr.strip() or f"exit code {result.return_code}"


def _remove_tree(ctx, path, what):
    if not path or not os.path.lexists(path):
        return
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    except OSError as exc:
        ctx.out.warning(messages.uninstall_step_failed(
            what, getattr(exc, "strerror", None) or str(exc)))


def _cli_self_uninstall(ctx):
    out = ctx.out
    if not system.Requirements(ctx.env, out).check():
        raise CliError(messages.uninstall_dependencies_down())
    if not out.confirm(messages.uninstall_confirmation(), ctx.args.option("yes")):
        return 0
    runtime = containers.Runtime(out=out, env=ctx.env, cwd=ctx.cwd, config=ctx.config)
    for what, list_args, remove_args in _RESOURCES:
        listed = runtime.run(list_args)
        if not listed.succeeded:
            out.warning(messages.uninstall_step_failed(what, _failure(listed)))
            continue
        ids = list(dict.fromkeys(line.strip() for line in listed.stdout.splitlines()
                                 if line.strip()))
        if ids:
            removed = runtime.run(remove_args + ids)
            if not removed.succeeded:
                out.warning(messages.uninstall_step_failed(what, _failure(removed)))
    projects = ctx.db.get_projects() if ctx.db is not None else []
    if ctx.db is not None:
        ctx.db.close()
    out.disable_log()
    for project in projects:
        _remove_tree(ctx, project["path"], f"project '{project['name']}'")
    _remove_tree(ctx, ctx.config.root_dir(), "the AppCtl root directory")
    archive = system.archive_path()
    if archive:
        _remove_tree(ctx, archive, "the AppCtl binary")
    out.success(messages.uninstall_completed())
    return 0


# --- registration ----------------------------------------------------------------------

def register(tree):
    r = tree.register
    r("cli", description="Reviews current appctl info, checks for updates, and manages appctl.")
    r("cli alias", _cli_alias, alias="aliases", synopsis="[--format=<format>]",
      description="Lists available aliases.", defaults={"format": "yaml"},
      longdesc="Prints every registered alias with its definition, as YAML (default) "
               "or JSON.")
    r("cli check-update", _cli_check_update,
      synopsis=f"[--patch] [--minor] [--major] {_LIST_FORMAT}",
      description="Checks to see if there is a newer version of appctl available.",
      defaults={"format": "table"},
      longdesc="Queries the releases API and lists newer versions. --patch, --minor and "
               "--major only list updates of that type; when several are given, the last "
               "one wins.")
    r("cli cmd-dump", _cli_cmd_dump,
      description="Dumps the list of installed commands, as JSON.")
    r("cli completions", _cli_completions, alias="completion",
      synopsis="--line=<line> --point=<point> [--shell=<shell>]",
      description="Generates tab completion strings.", defaults={"shell": "bash"},
      longdesc="Completes the command line --line at cursor position --point for the "
               "bash (default) or zsh shell.")
    r("cli has-command", _cli_has_command, synopsis="<command-name>...",
      description="Detects if a command exists.",
      longdesc="Exits with 0 when the command is registered and 1 otherwise, without "
               "printing anything.")
    r("cli info", _cli_info, synopsis="[--format=<format>]",
      description="Prints various details about the appctl environment.",
      defaults={"format": "list"})
    r("cli migrate", _cli_migrate,
      description="Runs pending migrations and upgrades containers to the current version.")
    r("cli param-dump", _cli_param_dump, synopsis="[--with-values] [--format=<format>]",
      description="Dumps the list of global parameters, as JSON or in var_export format.",
      defaults={"format": "json"})
    r("cli self-uninstall", _cli_self_uninstall, synopsis="[--yes]",
      description="Removes appctl, its containers, networks, volumes, images, projects "
                  "and data.")
    r("cli update", _cli_update,
      synopsis="[--stable] [--nightly] [--yes] [--archive=<archive-path>] [--path=<path>]",
      description="Updates appctl to the latest release.",
      longdesc="Downloads a newer distribution archive, validates it and replaces the "
               "running binary. --stable installs the latest stable release and "
               "--nightly the latest nightly build. --archive extracts a local .zip or "
               ".tar.gz archive into --path (the current directory by default) instead.")
    r("cli version", _cli_version, description="Prints appctl version.")
