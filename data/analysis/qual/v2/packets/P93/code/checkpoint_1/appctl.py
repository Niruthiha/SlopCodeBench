#!/usr/bin/env python3
"""appctl - a hierarchical command-line tool.

Usage:
    python appctl.py [<command>] [<subcommand>] [<args>] [--<flags>]
"""

import json
import os
import re
import sys

VERSION = "1.0.0"
PROG = "appctl"
STRICT_ENV = "APPCTL_STRICT_ARGS_MODE"
SUGGESTION_THRESHOLD = 2


# ---------------------------------------------------------------------------
# Errors and output helpers
# ---------------------------------------------------------------------------

class AppctlExit(Exception):
    """Raised to terminate the program with a given exit code."""

    def __init__(self, code=0):
        super().__init__(code)
        self.code = code


class SynopsisError(ValueError):
    """Raised when a synopsis string contains a malformed token."""


class Runtime:
    quiet = False
    debug = False
    config = {}


def out(text=""):
    sys.stdout.write(text + "\n")


def success(message):
    if not Runtime.quiet:
        out("Success: " + message)


def warning(message):
    sys.stderr.write("Warning: " + message + "\n")


def debug(message):
    if Runtime.debug:
        sys.stderr.write("Debug: " + message + "\n")


def error(message, code=1):
    sys.stderr.write("Error: " + message + "\n")
    raise AppctlExit(code)


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

# Curated synonyms for common command-name variants. A synonym is only
# suggested when the target is actually registered among the candidates.
SYNONYMS = {
    "add": "create",
    "check": "check-update",
    "clear": "flush",
    "conf": "config",
    "configure": "config",
    "decrement": "decr",
    "del": "delete",
    "destroy": "delete",
    "directory": "dir",
    "erase": "delete",
    "exec": "eval",
    "exec-file": "eval-file",
    "increment": "incr",
    "info": "get",
    "lang": "locale",
    "language": "locale",
    "ls": "list",
    "make": "create",
    "new": "create",
    "number": "count",
    "regen": "regenerate",
    "remove": "delete",
    "rep": "replace",
    "repl": "replace",
    "rm": "delete",
    "settings": "config",
    "show": "get",
    "trash": "delete",
    "v": "version",
    "ver": "version",
}


def levenshtein(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def sort_key(name):
    return (name.lower(), name)


def get_suggestion(word, candidates, threshold=SUGGESTION_THRESHOLD, synonyms=True):
    """Return the closest candidate to ``word`` or None (deterministic)."""
    candidates = sorted(set(candidates), key=sort_key)
    if not candidates:
        return None
    lowered = word.lower()
    if synonyms:
        target = SYNONYMS.get(lowered)
        if target is not None and target in candidates:
            return target
    best, best_dist = None, None
    for candidate in candidates:
        dist = levenshtein(lowered, candidate.lower())
        if best_dist is None or dist < best_dist:
            best, best_dist = candidate, dist
    if best_dist is not None and best_dist <= threshold:
        return best
    return None


# ---------------------------------------------------------------------------
# Synopsis parsing
# ---------------------------------------------------------------------------

_P_NAME = r"[a-z\-_0-9]+"
_P_VALUE = r"[a-zA-Z\-_|,0-9]+"


def _strip_optional(token):
    if len(token) >= 2 and token.startswith("[") and token.endswith("]"):
        return True, token[1:-1]
    return False, token


def _strip_repeating(token):
    if token.endswith("..."):
        return True, token[:-3]
    return False, token


def classify_token(token):
    """Classify a single synopsis token into a parameter spec dict."""
    param = {"token": token}
    param["optional"], body = _strip_optional(token)
    param["repeating"], body = _strip_repeating(body)

    if body == "--<field>=<value>":
        param["type"] = "generic"
        return param

    match = re.fullmatch(r"<(%s)>" % _P_VALUE, body)
    if match:
        param["type"] = "positional"
        param["name"] = match.group(1)
        return param

    match = re.match(r"--(\[no-\])?(%s)" % _P_NAME, body)
    if match:
        param["name"] = match.group(2)
        param["negatable"] = bool(match.group(1))
        rest = body[match.end():]
        if rest == "":
            param["type"] = "flag"
            return param
        value_optional, rest = _strip_optional(rest)
        value_match = re.fullmatch(r"=<(%s)>" % _P_VALUE, rest)
        if value_match:
            param["type"] = "assoc"
            param["value"] = {"optional": value_optional, "name": value_match.group(1)}
            return param

    return {"token": token, "type": "unknown", "optional": False, "repeating": False}


def parse_synopsis(synopsis, strict=False):
    """Parse a synopsis string into a list of parameter specs.

    With ``strict=True`` a malformed token raises :class:`SynopsisError`.
    """
    params = []
    for token in (synopsis or "").split():
        param = classify_token(token)
        if strict and param["type"] == "unknown":
            raise SynopsisError("Invalid synopsis token: '%s'" % token)
        params.append(param)
    return params


# ---------------------------------------------------------------------------
# Command tree
# ---------------------------------------------------------------------------

class Command:
    def __init__(self, name, parent=None, description="", synopsis="", alias=None,
                 handler=None, defaults=None, longdesc=""):
        self.name = name
        self.parent = parent
        self.description = description
        self.synopsis = " ".join((synopsis or "").split())
        self.alias = alias
        self.handler = handler
        self.defaults = dict(defaults or {})
        self.longdesc = longdesc
        self.subcommands = {}
        self.params = parse_synopsis(self.synopsis, strict=True)

    # -- tree helpers ------------------------------------------------------
    @property
    def path(self):
        parts = []
        node = self
        while node is not None and node.parent is not None:
            parts.append(node.name)
            node = node.parent
        return " ".join(reversed(parts))

    def add_subcommand(self, command):
        command.parent = self
        self.subcommands[command.name] = command

    def sorted_subcommands(self):
        return [self.subcommands[k] for k in sorted(self.subcommands, key=sort_key)]

    def find_subcommand(self, name):
        if name in self.subcommands:
            return self.subcommands[name]
        for sub in self.sorted_subcommands():
            if sub.alias and sub.alias == name:
                return sub
        return None

    def can_have_subcommands(self):
        return bool(self.subcommands)

    # -- usage helpers -----------------------------------------------------
    def usage_line(self):
        line = "%s %s" % (PROG, self.path) if self.path else PROG
        if self.subcommands and self.handler is None:
            return line + " <command>"
        if self.synopsis:
            line += " " + self.synopsis
        return line

    def show_usage(self):
        if self.subcommands and self.handler is None:
            lines = [sub.usage_line() for sub in self.sorted_subcommands()]
            for i, line in enumerate(lines):
                out(("usage: " if i == 0 else "   or: ") + line)
            out()
            out("See '%s help %s <command>' for more information on a specific command."
                % (PROG, self.path))
        else:
            out("usage: " + self.usage_line())

    def known_assoc(self):
        return [p["name"] for p in self.params if p["type"] in ("assoc", "flag")]


ROOT = Command("", description="Manage applications from the command line.")


def register(path, description="", synopsis="", alias=None, handler=None,
             defaults=None, longdesc=""):
    """Register a command (and any missing parent namespaces)."""
    parse_synopsis(synopsis, strict=True)
    parts = path.split()
    node = ROOT
    for part in parts[:-1]:
        child = node.subcommands.get(part)
        if child is None:
            child = Command(part)
            node.add_subcommand(child)
        node = child
    existing = node.subcommands.get(parts[-1])
    command = Command(parts[-1], description=description, synopsis=synopsis,
                      alias=alias, handler=handler, defaults=defaults, longdesc=longdesc)
    if existing is not None:
        for sub in existing.subcommands.values():
            command.add_subcommand(sub)
    node.add_subcommand(command)
    return command


def iter_commands(node=None):
    node = node or ROOT
    for sub in node.sorted_subcommands():
        yield sub
        yield from iter_commands(sub)


def unknown_command_error(name, parent):
    if parent is ROOT:
        message = ("'%s' is not a registered %s command. See '%s help' for available commands."
                   % (name, PROG, PROG))
    else:
        message = ("'%s' is not a registered subcommand of '%s'. See '%s help %s' for "
                   "available subcommands." % (name, parent.path, PROG, parent.path))
    suggestion = get_suggestion(name, parent.subcommands.keys())
    if suggestion:
        message += "\nDid you mean '%s'?" % suggestion
    error(message)


def resolve_command(positionals):
    """Walk the tree. Returns (command, remaining_positionals)."""
    node = ROOT
    remaining = list(positionals)
    while remaining and node.can_have_subcommands():
        token = remaining[0]
        child = node.find_subcommand(token)
        if child is None:
            if node.handler is not None:
                break
            unknown_command_error(token, node)
        node = child
        remaining.pop(0)
    return node, remaining


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

GLOBAL_PARAMS = parse_synopsis(
    "[--path=<path>] [--url=<url>] [--user=<id|login|email>] "
    "[--skip-plugins[=<plugins>]] [--skip-themes[=<themes>]] [--skip-packages] "
    "[--require=<path>] [--exec=<php-code>] [--context=<context>] [--[no-]color] "
    "[--debug[=<group>]] [--prompt[=<assoc>]] [--quiet]", strict=True)
GLOBAL_NAMES = {p["name"] for p in GLOBAL_PARAMS}


def parse_token(token):
    """Return (key, value) for an option token, or None for a positional."""
    if not token.startswith("--") or token == "--":
        return None
    body = token[2:]
    if "=" in body:
        key, value = body.split("=", 1)
        return key, value
    if body.startswith("no-") and len(body) > 3:
        return body[3:], False
    return body, True


def split_args(tokens, strict):
    """Split raw tokens into positionals, command assoc args and global config."""
    positionals = []
    assoc = []
    runtime = {}
    seen_positional = False
    positional_only = False
    for token in tokens:
        if positional_only:
            positionals.append(token)
            seen_positional = True
            continue
        if token == "--":
            positional_only = True
            continue
        parsed = parse_token(token)
        if parsed is None:
            positionals.append(token)
            seen_positional = True
            continue
        key, value = parsed
        is_global = key in GLOBAL_NAMES and not (strict and seen_positional)
        if is_global:
            runtime[key] = value
        else:
            assoc.append((key, value))
    return positionals, assoc, runtime


def rewrite_args(tokens):
    """Apply the --help and --version rewrites."""
    head = tokens
    tail = []
    if "--" in tokens:
        idx = tokens.index("--")
        head, tail = tokens[:idx], tokens[idx:]

    if "--help" in head:
        kept = [t for t in head if t != "--help"]
        new = ["help"]
        for token in kept + tail:
            parsed = parse_token(token)
            if parsed is None or token == "--":
                if token != "--":
                    new.append(token)
            elif parsed[0] in GLOBAL_NAMES:
                new.append(token)
        return new

    if "--version" in head and not tail:
        rest = [t for t in head if t != "--version"]
        if all(parse_token(t) is not None for t in rest):
            return ["cli", "version"] + rest
    return tokens


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_and_prepare(command, args, assoc_list):
    params = command.params
    positional_specs = [p for p in params if p["type"] == "positional"]
    assoc_specs = [p for p in params if p["type"] in ("assoc", "flag")]
    has_generic = any(p["type"] == "generic" for p in params)

    # 1. Required positionals.
    required = 0
    for spec in positional_specs:
        if not spec["optional"]:
            required += 1
    if len(args) < required:
        command.show_usage()
        raise AppctlExit(1)

    # 2. Excess positionals.
    if not any(p["repeating"] for p in positional_specs):
        if len(args) > len(positional_specs):
            extra = args[len(positional_specs):]
            error("Too many positional arguments: " + " ".join(extra))

    assoc = {}
    for key, value in assoc_list:
        assoc[key] = value

    # 3/4. Associative arguments.
    errors = []
    known = [p["name"] for p in assoc_specs]
    for spec in assoc_specs:
        key = spec["name"]
        if spec["type"] == "assoc":
            present = key in assoc
            value = assoc.get(key)
            if not spec["optional"]:
                if not present or value is True or value is False or value == "":
                    errors.append("missing --%s parameter" % key)
                    continue
            elif present and (value is True or value is False) and not spec["value"]["optional"]:
                warning("--%s parameter needs a value" % key)
                del assoc[key]
        else:
            if not spec["optional"] and key not in assoc:
                errors.append("missing --%s parameter" % key)

    if not has_generic:
        seen = set()
        for key, _ in assoc_list:
            if key in known or key in seen:
                continue
            seen.add(key)
            message = "unknown --%s parameter" % key
            suggestion = get_suggestion(key, known, synonyms=False)
            if suggestion:
                message += "\nDid you mean '--%s'?" % suggestion
            errors.append(message)

    if errors:
        error("Parameter errors:\n" + "\n".join(errors))

    # Apply defaults.
    args = list(args)
    for index, spec in enumerate(positional_specs):
        if index >= len(args) and spec["name"] in command.defaults and not spec["repeating"]:
            args.append(command.defaults[spec["name"]])
    for spec in assoc_specs:
        if spec["name"] not in assoc and spec["name"] in command.defaults:
            assoc[spec["name"]] = command.defaults[spec["name"]]
    return args, assoc


# ---------------------------------------------------------------------------
# Output formatting helpers for handlers
# ---------------------------------------------------------------------------

def format_items(fmt, items, fields):
    fmt = fmt or "table"
    if fmt == "count":
        out(str(len(items)))
    elif fmt == "ids":
        out(" ".join(str(item.get(fields[0], "")) for item in items))
    elif fmt == "json":
        out(json.dumps([{f: item.get(f) for f in fields} for item in items]))
    elif fmt == "csv":
        out(",".join(fields))
        for item in items:
            out(",".join(str(item.get(f, "")) for f in fields))
    elif fmt == "yaml":
        out("---")
        for item in items:
            for i, f in enumerate(fields):
                out(("- " if i == 0 else "  ") + "%s: %s" % (f, item.get(f, "")))
    elif fmt == "table":
        widths = {f: max([len(f)] + [len(str(item.get(f, ""))) for item in items]) for f in fields}
        sep = "+" + "+".join("-" * (widths[f] + 2) for f in fields) + "+"
        out(sep)
        out("| " + " | ".join(f.ljust(widths[f]) for f in fields) + " |")
        out(sep)
        for item in items:
            out("| " + " | ".join(str(item.get(f, "")).ljust(widths[f]) for f in fields) + " |")
        out(sep)
    else:
        error("Invalid format: %s" % fmt)


def render_items(assoc, items, default_fields):
    if assoc.get("field"):
        for item in items:
            out(str(item.get(assoc["field"], "")))
        return
    fields = default_fields
    if isinstance(assoc.get("fields"), str) and assoc["fields"]:
        fields = [f.strip() for f in assoc["fields"].split(",") if f.strip()]
    format_items(assoc.get("format"), items, fields)


def render_value(value, fmt):
    if fmt == "json":
        out(json.dumps(value))
    else:
        out(str(value))


def describe(**kwargs):
    return ", ".join("%s: %s" % (k, v) for k, v in kwargs.items())


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

def column_listing(commands):
    if not commands:
        return []
    width = max(len(c.name) for c in commands)
    return ["  %s  %s" % (c.name.ljust(width), c.description) for c in commands]


def show_root_help():
    out("usage: %s <command> [<subcommand>] [<args>] [--<flags>]" % PROG)
    out()
    out(ROOT.description)
    out()
    out("Available commands:")
    out()
    for line in column_listing(ROOT.sorted_subcommands()):
        out(line)
    out()
    out("See '%s help <command>' for more information on a specific command." % PROG)


def show_command_help(command):
    out("NAME")
    out()
    out("  %s %s" % (PROG, command.path))
    out()
    if command.description:
        out("DESCRIPTION")
        out()
        out("  " + command.description)
        out()
    out("SYNOPSIS")
    out()
    out("  " + command.usage_line())
    out()
    if command.alias:
        out("ALIAS")
        out()
        out("  " + command.alias)
        out()
    if command.handler is not None and command.params:
        out("OPTIONS")
        out()
        for spec in command.params:
            out("  " + spec["token"])
            name = spec.get("name")
            if name and name in command.defaults:
                out("    default: %s" % format_default(command.defaults[name]))
        out()
    if command.longdesc:
        out(command.longdesc.rstrip())
        out()
    if command.subcommands:
        out("SUBCOMMANDS")
        out()
        for line in column_listing(command.sorted_subcommands()):
            out(line)
        out()
        out("See '%s help %s <command>' for more information on a specific command."
            % (PROG, command.path))


def format_default(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def cmd_help(args, assoc):
    if not args:
        show_root_help()
        return
    command, remaining = resolve_command(args)
    if remaining:
        unknown_command_error(remaining[0], command)
    show_command_help(command)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_cli_version(args, assoc):
    out("%s %s" % (PROG, VERSION))


def cmd_cli_info(args, assoc):
    info = {
        "os": sys.platform,
        "python_binary": sys.executable,
        "python_version": sys.version.split()[0],
        "appctl_version": VERSION,
        "strict_args_mode": bool(os.environ.get(STRICT_ENV)),
    }
    if assoc.get("format") == "json":
        out(json.dumps(info))
    else:
        width = max(len(k) for k in info)
        for key, value in info.items():
            out("%s  %s" % (key.ljust(width), format_default(value)))


def cmd_cli_has_command(args, assoc):
    node = ROOT
    for part in args[0].split():
        node = node.find_subcommand(part) if node else None
        if node is None:
            raise AppctlExit(1)
    raise AppctlExit(0)


def _dump(command):
    data = {
        "name": command.name,
        "description": command.description,
        "synopsis": command.synopsis,
        "alias": command.alias,
        "subcommands": [_dump(s) for s in command.sorted_subcommands()],
    }
    return data


def cmd_cli_cmd_dump(args, assoc):
    data = _dump(ROOT)
    data["name"] = PROG
    out(json.dumps(data))


def cmd_cli_check_update(args, assoc):
    success("appctl is at the latest version.")


def cmd_cli_alias_list(args, assoc):
    render_value({}, assoc.get("format"))


def cmd_cli_alias_add(args, assoc):
    success("Added '%s' alias." % args[0])


def cmd_cli_alias_delete(args, assoc):
    success("Deleted '%s' alias." % args[0])


SAMPLE_SITES = [
    {"name": "main", "url": "https://example.com", "type": "standard", "status": "active"},
    {"name": "blog", "url": "https://blog.example.com", "type": "blog", "status": "active"},
]


def cmd_site_create(args, assoc):
    name = args[0]
    title = assoc.get("title") or name
    if assoc.get("porcelain"):
        out(name)
        return
    success("Created site '%s' (%s)." % (name, describe(type=assoc.get("type"), title=title)))


def cmd_site_delete(args, assoc):
    if not assoc.get("yes"):
        out("Deleting site '%s' (pass --yes to skip confirmation)." % args[0])
    success("Deleted site '%s'." % args[0])


def cmd_site_list(args, assoc):
    render_items(assoc, SAMPLE_SITES, ["name", "url", "type", "status"])


def cmd_site_update(args, assoc):
    fields = {k: v for k, v in assoc.items()}
    if not fields:
        error("Need some fields to update.")
    success("Updated site '%s' (%s)." % (args[0], describe(**fields)))


def cmd_site_activate(args, assoc):
    for name in args:
        success("Site '%s' activated." % name)


def cmd_site_deactivate(args, assoc):
    for name in args:
        success("Site '%s' deactivated." % name)


def cmd_site_empty(args, assoc):
    success("The site at '%s' was emptied." % (Runtime.config.get("url") or "default"))


def cmd_site_meta_get(args, assoc):
    render_value("", assoc.get("format"))


def cmd_site_meta_set(args, assoc):
    success("Updated meta '%s' of site '%s' to '%s'." % (args[1], args[0], args[2]))


def cmd_site_meta_delete(args, assoc):
    success("Deleted meta '%s' of site '%s'." % (args[1], args[0]))


def cmd_site_meta_list(args, assoc):
    render_items(assoc, [], ["site", "meta_key", "meta_value"])


CONFIG = {"DB_NAME": "app", "DB_USER": "root", "DB_HOST": "localhost", "DEBUG": "false"}


def cmd_config_get(args, assoc):
    if args[0] not in CONFIG:
        error("The constant or variable '%s' is not defined in the config file." % args[0])
    render_value(CONFIG[args[0]], assoc.get("format"))


def cmd_config_set(args, assoc):
    success("Updated the constant '%s' in the config file with the value '%s' (%s)."
            % (args[0], args[1], describe(type=assoc.get("type"))))


def cmd_config_delete(args, assoc):
    if args[0] not in CONFIG:
        error("The constant or variable '%s' is not defined in the config file." % args[0])
    success("Deleted the constant '%s' from the config file." % args[0])


def cmd_config_list(args, assoc):
    items = [{"name": k, "value": v, "type": "constant"} for k, v in CONFIG.items()
             if not args or any(f in k for f in args)]
    render_items(assoc, items, ["name", "value", "type"])


def cmd_config_path(args, assoc):
    out(os.path.join(Runtime.config.get("path") or os.getcwd(), "app-config.php"))


def cmd_config_create(args, assoc):
    success("Generated config file (%s)." % describe(
        dbname=assoc["dbname"], dbuser=assoc["dbuser"], dbhost=assoc.get("dbhost"),
        dbprefix=assoc.get("dbprefix")))


def cmd_cache_flush(args, assoc):
    success("The cache was flushed.")


def cmd_cache_get(args, assoc):
    error("Object with key '%s' and group '%s' not found." % (args[0], args[1]))


def cmd_cache_set(args, assoc):
    success("Set object '%s' in group '%s' (%s)." % (args[0], args[2], describe(expiration=args[3])))


def cmd_cache_delete(args, assoc):
    success("Object deleted.")


def cmd_db_create(args, assoc):
    success("Database created.")


def cmd_db_drop(args, assoc):
    success("Database dropped.")


def cmd_db_reset(args, assoc):
    success("Database reset.")


def cmd_db_export(args, assoc):
    name = args[0] if args else "database.sql"
    if assoc.get("porcelain"):
        out(name)
    else:
        success("Exported to '%s'." % name)


def cmd_db_import(args, assoc):
    success("Imported from '%s'." % args[0])


def cmd_db_query(args, assoc):
    out(args[0] if args else "")


def cmd_db_size(args, assoc):
    render_items(assoc, [{"Name": "app", "Size": "0 B"}], ["Name", "Size"])


OPTIONS = {"siteurl": "https://example.com", "blogname": "Example", "admin_email": "admin@example.com"}


def cmd_option_get(args, assoc):
    if args[0] not in OPTIONS:
        error("Could not get '%s' option. Does it exist?" % args[0])
    render_value(OPTIONS[args[0]], assoc.get("format"))


def cmd_option_add(args, assoc):
    success("Added '%s' option (%s)." % (args[0], describe(autoload=assoc.get("autoload"))))


def cmd_option_update(args, assoc):
    success("Updated '%s' option (%s)." % (args[0], describe(autoload=assoc.get("autoload"))))


def cmd_option_delete(args, assoc):
    for key in args:
        success("Deleted '%s' option." % key)


def cmd_option_list(args, assoc):
    import fnmatch
    pattern = assoc.get("search")
    items = [{"option_name": k, "option_value": v} for k, v in OPTIONS.items()
             if not pattern or fnmatch.fnmatch(k, pattern)]
    render_items(assoc, items, ["option_name", "option_value"])


SAMPLE_PLUGINS = [
    {"name": "akismet", "status": "active", "update": "none", "version": "5.3"},
    {"name": "hello", "status": "inactive", "update": "none", "version": "1.7.2"},
]


def _plugin_targets(args, assoc, verb):
    if assoc.get("all"):
        return [p["name"] for p in SAMPLE_PLUGINS]
    if not args:
        error("Please specify one or more plugins, or use --all.")
    return args


def cmd_plugin_install(args, assoc):
    for name in args:
        out("Installing %s%s" % (name, " (%s)" % assoc["version"] if assoc.get("version") else ""))
        if assoc.get("activate"):
            out("Activating '%s'..." % name)
    success("Installed %d of %d plugins." % (len(args), len(args)))


def cmd_plugin_activate(args, assoc):
    targets = _plugin_targets(args, assoc, "activate")
    for name in targets:
        out("Plugin '%s' activated." % name)
    success("Activated %d of %d plugins." % (len(targets), len(targets)))


def cmd_plugin_deactivate(args, assoc):
    targets = _plugin_targets(args, assoc, "deactivate")
    for name in targets:
        out("Plugin '%s' deactivated." % name)
    success("Deactivated %d of %d plugins." % (len(targets), len(targets)))


def cmd_plugin_delete(args, assoc):
    targets = _plugin_targets(args, assoc, "delete")
    success("Deleted %d of %d plugins." % (len(targets), len(targets)))


def cmd_plugin_uninstall(args, assoc):
    targets = _plugin_targets(args, assoc, "uninstall")
    success("Uninstalled %d of %d plugins." % (len(targets), len(targets)))


def cmd_plugin_update(args, assoc):
    targets = _plugin_targets(args, assoc, "update")
    if assoc.get("dry-run"):
        out("Available plugin updates: none")
        return
    success("Plugins already updated: %d." % len(targets))


def cmd_plugin_list(args, assoc):
    items = SAMPLE_PLUGINS
    if isinstance(assoc.get("status"), str):
        items = [p for p in items if p["status"] == assoc["status"]]
    render_items(assoc, items, ["name", "status", "update", "version"])


def cmd_plugin_status(args, assoc):
    if args:
        for p in SAMPLE_PLUGINS:
            if p["name"] == args[0]:
                out("Plugin %s details:" % p["name"])
                out("    Status: %s" % p["status"].capitalize())
                out("    Version: %s" % p["version"])
                return
        error("The '%s' plugin could not be found." % args[0])
    out("%d installed plugins:" % len(SAMPLE_PLUGINS))
    for p in SAMPLE_PLUGINS:
        out("  %s %s %s" % ("A" if p["status"] == "active" else "I", p["name"], p["version"]))


SAMPLE_THEMES = [
    {"name": "default", "status": "active", "update": "none", "version": "1.0"},
    {"name": "classic", "status": "inactive", "update": "none", "version": "2.1"},
]


def cmd_theme_activate(args, assoc):
    success("Switched to '%s' theme." % args[0])


def cmd_theme_install(args, assoc):
    for name in args:
        out("Installing %s" % name)
    success("Installed %d of %d themes." % (len(args), len(args)))


def cmd_theme_delete(args, assoc):
    names = [t["name"] for t in SAMPLE_THEMES] if assoc.get("all") else args
    if not names:
        error("Please specify one or more themes, or use --all.")
    success("Deleted %d of %d themes." % (len(names), len(names)))


def cmd_theme_list(args, assoc):
    render_items(assoc, SAMPLE_THEMES, ["name", "status", "update", "version"])


SAMPLE_POSTS = [
    {"ID": 1, "post_title": "Hello world!", "post_type": "post", "post_status": "publish"},
    {"ID": 2, "post_title": "Sample Page", "post_type": "page", "post_status": "publish"},
]


def cmd_post_create(args, assoc):
    if assoc.get("porcelain"):
        out("3")
        return
    fields = {k: v for k, v in assoc.items() if k != "porcelain"}
    success("Created post 3 (%s)." % describe(**fields))


def cmd_post_get(args, assoc):
    for post in SAMPLE_POSTS:
        if str(post["ID"]) == args[0]:
            if assoc.get("field"):
                out(str(post.get(assoc["field"], "")))
            else:
                render_items(assoc, [post], list(post.keys()))
            return
    error("Could not find the post with ID %s." % args[0])


def cmd_post_list(args, assoc):
    items = SAMPLE_POSTS
    filters = {k: v for k, v in assoc.items() if k not in ("format", "field", "fields")}
    for key, value in filters.items():
        items = [p for p in items if str(p.get(key)) == str(value)]
    render_items(assoc, items, ["ID", "post_title", "post_type", "post_status"])


def cmd_post_update(args, assoc):
    fields = {k: v for k, v in assoc.items()}
    if not fields:
        error("Need some fields to update.")
    for post_id in args:
        success("Updated post %s." % post_id)


def cmd_post_delete(args, assoc):
    for post_id in args:
        if assoc.get("force"):
            success("Deleted post %s." % post_id)
        else:
            success("Trashed post %s." % post_id)


SAMPLE_USERS = [
    {"ID": 1, "user_login": "admin", "user_email": "admin@example.com", "roles": "administrator"},
]


def cmd_user_create(args, assoc):
    if assoc.get("porcelain"):
        out("2")
        return
    success("Created user 2 (%s)." % describe(login=args[0], email=args[1], role=assoc.get("role")))


def cmd_user_delete(args, assoc):
    for user in args:
        success("Removed user %s%s." % (user, " (reassigned to %s)" % assoc["reassign"]
                                         if assoc.get("reassign") else ""))


def cmd_user_get(args, assoc):
    for user in SAMPLE_USERS:
        if args[0] in (str(user["ID"]), user["user_login"], user["user_email"]):
            if assoc.get("field"):
                out(str(user.get(assoc["field"], "")))
            else:
                render_items(assoc, [user], list(user.keys()))
            return
    error("Invalid user ID, email or login: '%s'" % args[0])


def cmd_user_list(args, assoc):
    items = SAMPLE_USERS
    if isinstance(assoc.get("role"), str):
        items = [u for u in items if u["roles"] == assoc["role"]]
    render_items(assoc, items, ["ID", "user_login", "user_email", "roles"])


def cmd_user_update(args, assoc):
    fields = {k: v for k, v in assoc.items() if k != "skip-email"}
    if not fields:
        error("Need some fields to update.")
    for user in args:
        success("Updated user %s." % user)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def build_registry():
    register("help", "Get help on appctl, or on a specific command.",
             "[<command>...]", handler=cmd_help)

    register("cli", "Review current appctl info, check for updates, or see defined aliases.")
    register("cli version", "Print appctl version.", "", handler=cmd_cli_version)
    register("cli info", "Print various details about the appctl environment.",
             "[--format=<format>]", handler=cmd_cli_info, defaults={"format": "list"})
    register("cli check-update", "Check to see if there is a newer version of appctl available.",
             "[--patch] [--minor] [--major] [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_cli_check_update, defaults={"format": "table"})
    register("cli has-command", "Detect if a command exists.", "<command_name>",
             handler=cmd_cli_has_command)
    register("cli cmd-dump", "Dump the list of installed commands, as JSON.", "",
             handler=cmd_cli_cmd_dump)
    register("cli alias", "Retrieve, set, and delete appctl aliases.")
    register("cli alias list", "List available appctl aliases.", "[--format=<format>]",
             handler=cmd_cli_alias_list, defaults={"format": "yaml"})
    register("cli alias add", "Create an alias.",
             "<key> [--set-user=<user>] [--set-url=<url>] [--set-path=<path>] [--grouping=<grouping>]",
             handler=cmd_cli_alias_add)
    register("cli alias delete", "Delete an alias.", "<key>", handler=cmd_cli_alias_delete)

    register("site", "Create, delete, list, and update sites.")
    register("site create", "Create a site.",
             "<site-name> [--type=<type>] [--title=<title>] [--email=<email>] [--porcelain]",
             handler=cmd_site_create, defaults={"type": "standard"})
    register("site delete", "Delete a site.", "<site-name> [--yes] [--keep-tables]",
             alias="rm", handler=cmd_site_delete)
    register("site list", "List all sites.",
             "[--field=<field>] [--fields=<fields>] [--format=<format>]",
             alias="ls", handler=cmd_site_list, defaults={"format": "table"})
    register("site update", "Update one or more fields of a site.",
             "<site-name> [--<field>=<value>]", handler=cmd_site_update)
    register("site activate", "Activate one or more sites.", "<site-name>...",
             handler=cmd_site_activate)
    register("site deactivate", "Deactivate one or more sites.", "<site-name>...",
             handler=cmd_site_deactivate)
    register("site empty", "Empty a site of its content.", "[--uploads] [--yes]",
             handler=cmd_site_empty)
    register("site meta", "Add, update, get, and delete site metadata.")
    register("site meta get", "Get a meta field.", "<site-name> <key> [--format=<format>]",
             handler=cmd_site_meta_get, defaults={"format": "var_export"})
    register("site meta set", "Set a meta field.", "<site-name> <key> <value> [--format=<format>]",
             handler=cmd_site_meta_set, defaults={"format": "plaintext"})
    register("site meta delete", "Delete a meta field.", "<site-name> <key> [--all]",
             handler=cmd_site_meta_delete)
    register("site meta list", "List all metadata associated with a site.",
             "<site-name> [--keys=<keys>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_site_meta_list, defaults={"format": "table"})

    register("config", "Generate and read the application configuration file.", alias="cfg")
    register("config get", "Get the value of a specific constant or variable.",
             "<name> [--type=<type>] [--format=<format>]",
             handler=cmd_config_get, defaults={"type": "all", "format": "var_export"})
    register("config set", "Set the value of a specific constant or variable.",
             "<name> <value> [--add] [--raw] [--anchor=<anchor>] [--type=<type>]",
             handler=cmd_config_set, defaults={"type": "all"})
    register("config delete", "Delete a specific constant or variable.",
             "<name> [--type=<type>]", handler=cmd_config_delete, defaults={"type": "all"})
    register("config list", "List variables, constants, and file includes.",
             "[<filter>...] [--fields=<fields>] [--format=<format>] [--strict]",
             handler=cmd_config_list, defaults={"format": "table"})
    register("config path", "Get the path to the configuration file.", "",
             handler=cmd_config_path)
    register("config create", "Generate a configuration file.",
             "--dbname=<dbname> --dbuser=<dbuser> [--dbpass=<dbpass>] [--dbhost=<dbhost>] "
             "[--dbprefix=<dbprefix>] [--skip-check] [--force]",
             handler=cmd_config_create, defaults={"dbhost": "localhost", "dbprefix": "app_"})

    register("cache", "Add, remove, fetch, and flush the object cache.")
    register("cache flush", "Flush the object cache.", "", handler=cmd_cache_flush)
    register("cache get", "Get a value from the object cache.", "<key> [<group>]",
             handler=cmd_cache_get, defaults={"group": "default"})
    register("cache set", "Set a value to the object cache.",
             "<key> <value> [<group>] [<expiration>]", handler=cmd_cache_set,
             defaults={"group": "default", "expiration": 0})
    register("cache delete", "Remove a value from the object cache.", "<key> [<group>]",
             handler=cmd_cache_delete, defaults={"group": "default"})

    register("db", "Perform basic database operations.")
    register("db create", "Create a new database.", "", handler=cmd_db_create)
    register("db drop", "Delete the existing database.", "[--yes]", handler=cmd_db_drop)
    register("db reset", "Remove all tables from the database.", "[--yes]", handler=cmd_db_reset)
    register("db export", "Export the database to a file or to STDOUT.",
             "[<file>] [--tables=<tables>] [--exclude_tables=<tables>] [--porcelain]",
             handler=cmd_db_export)
    register("db import", "Import a database from a file or from STDIN.",
             "[<file>] [--skip-optimization]", handler=cmd_db_import,
             defaults={"file": "database.sql"})
    register("db query", "Execute a SQL query against the database.", "[<sql>]",
             handler=cmd_db_query)
    register("db size", "Display the database name and size.",
             "[--size_format=<format>] [--tables] [--format=<format>]",
             handler=cmd_db_size, defaults={"format": "table"})

    register("option", "Retrieve and set site options.")
    register("option get", "Get the value for an option.", "<key> [--format=<format>]",
             handler=cmd_option_get, defaults={"format": "var_export"})
    register("option add", "Add a new option value.",
             "<key> [<value>] [--format=<format>] [--autoload=<autoload>]",
             handler=cmd_option_add, defaults={"format": "plaintext", "autoload": "yes"})
    register("option update", "Update an option value.",
             "<key> [<value>] [--autoload=<autoload>] [--format=<format>]",
             handler=cmd_option_update, defaults={"format": "plaintext"})
    register("option delete", "Delete an option.", "<key>...", handler=cmd_option_delete)
    register("option list", "List options and their values.",
             "[--search=<pattern>] [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_option_list, defaults={"format": "table"})

    register("plugin", "Manage plugins.")
    register("plugin install", "Install one or more plugins.",
             "<plugin|zip|url>... [--version=<version>] [--force] [--activate]",
             handler=cmd_plugin_install)
    register("plugin activate", "Activate one or more plugins.",
             "[<plugin>...] [--all] [--network]", handler=cmd_plugin_activate)
    register("plugin deactivate", "Deactivate one or more plugins.",
             "[<plugin>...] [--uninstall] [--all] [--network]", handler=cmd_plugin_deactivate)
    register("plugin delete", "Delete plugin files without deactivating or uninstalling.",
             "[<plugin>...] [--all]", handler=cmd_plugin_delete)
    register("plugin uninstall", "Uninstall one or more plugins.",
             "[<plugin>...] [--deactivate] [--skip-delete] [--all]", handler=cmd_plugin_uninstall)
    register("plugin update", "Update one or more plugins.",
             "[<plugin>...] [--all] [--format=<format>] [--version=<version>] [--dry-run]",
             handler=cmd_plugin_update, defaults={"format": "table"})
    register("plugin list", "Get a list of plugins.",
             "[--status=<status>] [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_plugin_list, defaults={"format": "table"})
    register("plugin status", "Reveal the status of one or all plugins.", "[<plugin>]",
             handler=cmd_plugin_status)

    register("theme", "Manage themes.")
    register("theme activate", "Activate a theme.", "<theme>", handler=cmd_theme_activate)
    register("theme install", "Install one or more themes.",
             "<theme|zip|url>... [--version=<version>] [--force] [--activate]",
             handler=cmd_theme_install)
    register("theme delete", "Delete one or more themes.", "[<theme>...] [--all] [--force]",
             handler=cmd_theme_delete)
    register("theme list", "Get a list of themes.",
             "[--status=<status>] [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_theme_list, defaults={"format": "table"})

    register("post", "Manage posts, content, and meta.")
    register("post create", "Create a new post.",
             "[--post_title=<title>] [--post_type=<type>] [--post_status=<status>] "
             "[--<field>=<value>] [--porcelain]",
             handler=cmd_post_create, defaults={"post_type": "post", "post_status": "draft"})
    register("post get", "Get details about a post.",
             "<id> [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_post_get, defaults={"format": "table"})
    register("post list", "Get a list of posts.",
             "[--<field>=<value>] [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_post_list, defaults={"format": "table"})
    register("post update", "Update one or more existing posts.",
             "<id>... [--<field>=<value>]", handler=cmd_post_update)
    register("post delete", "Delete an existing post.", "<id>... [--force] [--defer-term-counting]",
             handler=cmd_post_delete)

    register("user", "Manage users, along with their roles, capabilities, and meta.")
    register("user create", "Create a new user.",
             "<user-login> <user-email> [--role=<role>] [--user_pass=<password>] "
             "[--display_name=<name>] [--send-email] [--porcelain]",
             handler=cmd_user_create, defaults={"role": "subscriber"})
    register("user delete", "Delete one or more users.",
             "<user>... [--network] [--reassign=<user-id>] [--yes]", handler=cmd_user_delete)
    register("user get", "Get details about a user.",
             "<user> [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_user_get, defaults={"format": "table"})
    register("user list", "List users.",
             "[--role=<role>] [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_user_list, defaults={"format": "table"})
    register("user update", "Update an existing user.",
             "<user>... [--user_pass=<password>] [--<field>=<value>] [--skip-email]",
             handler=cmd_user_update)


build_registry()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def apply_runtime_config(runtime):
    Runtime.config = runtime
    Runtime.quiet = bool(runtime.get("quiet"))
    Runtime.debug = runtime.get("debug") not in (None, False)
    if Runtime.debug:
        debug("Runtime config: %s" % json.dumps(runtime, sort_keys=True))


def run(argv):
    strict = bool(os.environ.get(STRICT_ENV))
    tokens = rewrite_args(list(argv))
    positionals, assoc_list, runtime = split_args(tokens, strict)
    apply_runtime_config(runtime)

    if not positionals:
        show_root_help()
        return 0

    command, remaining = resolve_command(positionals)
    debug("Running command: %s" % command.path)

    if command.handler is None:
        command.show_usage()
        return 0

    args, assoc = validate_and_prepare(command, remaining, assoc_list)
    command.handler(args, assoc)
    return 0


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    try:
        code = run(argv)
    except AppctlExit as exc:
        code = exc.code
    except BrokenPipeError:
        code = 0
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
