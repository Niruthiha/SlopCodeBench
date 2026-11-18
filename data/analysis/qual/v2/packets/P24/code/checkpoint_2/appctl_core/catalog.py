"""Built-in command catalog.

Secret: which commands exist, together with their synopses, aliases,
defaults, descriptions and what each handler does.
"""

import json

from . import config_spec, dispatch, formatter, help_text, messages, yaml_lite
from .errors import CliError
from .suggest import suggest

VERSION = "1.0.0"

_SITES = [
    {"name": "main", "type": "standard", "title": "Main Site", "status": "active"},
    {"name": "blog", "type": "blog", "title": "Company Blog", "status": "active"},
    {"name": "shop", "type": "store", "title": "Shop", "status": "archived"},
]
_PLUGINS = [
    {"name": "akismet", "status": "active", "version": "5.3"},
    {"name": "hello-dolly", "status": "inactive", "version": "1.7.2"},
]
_USERS = [
    {"ID": 1, "user_login": "admin", "user_email": "admin@example.com", "roles": "administrator"},
    {"ID": 2, "user_login": "editor", "user_email": "editor@example.com", "roles": "editor"},
]
_POSTS = [
    {"ID": 1, "post_title": "Hello world!", "post_status": "publish", "post_type": "post"},
    {"ID": 2, "post_title": "Sample Page", "post_status": "publish", "post_type": "page"},
]
_OPTIONS = {"blogname": "My Site", "siteurl": "https://example.com", "admin_email": "admin@example.com"}
_CONFIG = {"DB_NAME": "app", "DB_HOST": "localhost", "DEBUG": "false"}


# --- shared helpers -------------------------------------------------------

def _render(ctx, records, default_fields):
    args = ctx.args
    field = args.option("field")
    fields = [field] if field else (
        args.option("fields").split(",") if args.option("fields") else default_fields)
    fmt = args.option("format", "table")
    if field and fmt == "table":
        for record in records:
            ctx.out.line(str(record.get(field, "")))
        return 0
    try:
        ctx.out.line(formatter.render(records, fields, fmt))
    except ValueError:
        raise CliError(f"Invalid format: {fmt}. Supported formats: "
                       + ", ".join(formatter.supported_formats()))
    return 0


def _each(ctx, verb, noun):
    items = ctx.args.positionals
    for item in items:
        ctx.out.log(f"{verb} {noun} '{item}'.")
    ctx.out.success(f"{verb} {len(items)} of {len(items)} {noun}s.")
    return 0


def _filtered(records, key, value):
    return [r for r in records if value is None or str(r.get(key)) == str(value)]


def _require_targets_or_all(ctx, noun):
    if not ctx.args.positionals and not ctx.args.option("all"):
        raise CliError(f"Please specify one or more {noun}s, or use --all.")
    if ctx.args.option("all"):
        return [p["name"] for p in _PLUGINS]
    return ctx.args.positionals


# --- cache ----------------------------------------------------------------

def _cache_set(verb):
    def handler(ctx):
        key, value, group, expiration = ctx.args.positionals[:4]
        ctx.out.success(f"{verb} object '{key}' in group '{group}' "
                        f"(expires: {expiration}): {value}")
        return 0
    return handler


def _cache_step(sign):
    def handler(ctx):
        key, offset, group = ctx.args.positionals[:3]
        try:
            amount = int(offset)
        except ValueError:
            raise CliError(f"Offset must be an integer, got '{offset}'.")
        ctx.out.line(str(sign * amount))
        ctx.out.log(f"Adjusted '{key}' in group '{group}' by {sign * amount}.")
        return 0
    return handler


def _cache_get(ctx):
    key, group = ctx.args.positionals[:2]
    raise CliError(f"Object with key '{key}' and group '{group}' not found.")


def _cache_delete(ctx):
    key, group = ctx.args.positionals[:2]
    ctx.out.success(f"Object '{key}' deleted from group '{group}'.")
    return 0


def _cache_flush(ctx):
    ctx.out.success("The cache was flushed.")
    return 0


# --- cli ------------------------------------------------------------------

def _cli_version(ctx):
    ctx.out.line(f"appctl {VERSION}")
    return 0


def _cli_info(ctx):
    info = dict(ctx.config.as_dict(), version=VERSION)
    fmt = ctx.args.option("format")
    try:
        ctx.out.line(formatter.render_mapping(info, fmt))
    except ValueError:
        raise CliError(f"Invalid format: {fmt}. Supported formats: "
                       + ", ".join(formatter.supported_mapping_formats()))
    return 0


def _cli_has_command(ctx):
    words = " ".join(ctx.args.positionals).split()
    return 0 if ctx.tree.find(words) is not None else 1


def _cli_param_dump(ctx):
    dump = {}
    for param in config_spec.visible():
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
    return _dump_structure(ctx, dump)


def _dump_structure(ctx, data):
    fmt = ctx.args.option("format")
    if fmt == "json":
        ctx.out.line(json.dumps(data))
    elif fmt == "yaml":
        ctx.out.line("---\n" + yaml_lite.dump(data) if data else "--- {}")
    else:
        raise CliError(f"Invalid format: {fmt}. Supported formats: json, yaml")
    return 0


def _alias_definitions(ctx):
    registry = ctx.config.aliases()
    return registry.definitions() if registry is not None else {}


def _cli_alias_list(ctx):
    definitions = _alias_definitions(ctx)
    ordered = {name: definitions[name]
               for name in sorted(definitions, key=lambda n: (n.casefold(), n))}
    return _dump_structure(ctx, ordered)


def _cli_alias_get(ctx):
    name = ctx.args.positional(0)
    definitions = _alias_definitions(ctx)
    if name not in definitions:
        raise CliError(messages.alias_not_found(name, suggest(name, list(definitions))))
    value = definitions[name]
    if isinstance(value, dict):
        for key, item in value.items():
            ctx.out.line(f"{key}: {item}")
    elif isinstance(value, list):
        for item in value:
            ctx.out.line(f"- {item}")
    else:
        ctx.out.line(str(value))
    return 0


# --- config ---------------------------------------------------------------

def _config_get(ctx):
    name = ctx.args.positional(0)
    if name not in _CONFIG:
        raise CliError(f"The constant or variable '{name}' is not defined in the config file.")
    ctx.out.line(_CONFIG[name])
    return 0


def _config_set(ctx):
    name, value = ctx.args.positionals[:2]
    kind = ctx.args.option("type")
    raw = " (raw)" if ctx.args.option("raw") else ""
    ctx.out.success(f"Updated the {kind} '{name}' in the config file "
                    f"with the value '{value}'{raw}.")
    return 0


def _config_delete(ctx):
    name = ctx.args.positional(0)
    if name not in _CONFIG:
        raise CliError(f"The {ctx.args.option('type')} '{name}' is not defined in the config file.")
    ctx.out.success(f"Deleted '{name}' from the config file.")
    return 0


def _config_list(ctx):
    filters = ctx.args.positionals
    strict = ctx.args.option("strict")
    records = [{"name": k, "value": v} for k, v in _CONFIG.items()
               if not filters or any((f == k) if strict else (f in k) for f in filters)]
    return _render(ctx, records, ["name", "value"])


# --- help -----------------------------------------------------------------

def _help(ctx):
    words = ctx.args.positionals
    if not words:
        ctx.out.usage(help_text.top_level_help(ctx.tree))
        return 0
    node, _ = dispatch.resolve(ctx.tree, words)
    ctx.out.usage(help_text.command_help(node))
    return 0


# --- option ---------------------------------------------------------------

def _option_get(ctx):
    key = ctx.args.positional(0)
    if key not in _OPTIONS:
        raise CliError(f"Could not get '{key}' option. Does it exist?")
    ctx.out.line(_OPTIONS[key])
    return 0


def _option_write(verb):
    def handler(ctx):
        key = ctx.args.positional(0)
        value = ctx.args.positional(1)
        if value is None:
            raise CliError("Please provide a value for the option.")
        ctx.out.success(f"{verb} '{key}' option (autoload: {ctx.args.option('autoload')}).")
        return 0
    return handler


def _option_list(ctx):
    search = ctx.args.option("search")
    exclude = ctx.args.option("exclude")
    records = [{"option_name": k, "option_value": v} for k, v in _OPTIONS.items()
               if (search is None or search in k) and (exclude is None or exclude not in k)]
    return _render(ctx, records, ["option_name", "option_value"])


# --- plugin ---------------------------------------------------------------

def _plugin_bulk(verb):
    def handler(ctx):
        names = _require_targets_or_all(ctx, "plugin")
        for name in names:
            ctx.out.log(f"Plugin '{name}' {verb}.")
        ctx.out.success(f"{verb.capitalize()} {len(names)} of {len(names)} plugins.")
        return 0
    return handler


def _plugin_install(ctx):
    version = ctx.args.option("version")
    for name in ctx.args.positionals:
        suffix = f" (version {version})" if version else ""
        ctx.out.log(f"Installing {name}{suffix}...")
        if ctx.args.option("activate"):
            ctx.out.log(f"Plugin '{name}' activated.")
    count = len(ctx.args.positionals)
    ctx.out.success(f"Installed {count} of {count} plugins.")
    return 0


def _plugin_list(ctx):
    records = _filtered(_PLUGINS, "status", ctx.args.option("status"))
    return _render(ctx, records, ["name", "status", "version"])


# --- post -----------------------------------------------------------------

def _post_create(ctx):
    args = ctx.args
    if args.option("porcelain"):
        ctx.out.line("3")
    else:
        ctx.out.success(f"Created {args.option('type')} 3 "
                        f"'{args.option('title', '')}' with status {args.option('status')}.")
    return 0


def _post_get(ctx):
    post_id = ctx.args.positional(0)
    records = _filtered(_POSTS, "ID", post_id)
    if not records:
        raise CliError(f"Could not find the post with ID {post_id}.")
    return _render(ctx, records, list(records[0]))


def _post_list(ctx):
    records = list(_POSTS)
    for key, value in ctx.args.options().items():
        if key not in ("format", "field", "fields"):
            records = _filtered(records, key, value)
    return _render(ctx, records, ["ID", "post_title", "post_status", "post_type"])


def _update_fields(noun):
    def handler(ctx):
        fields = {k: v for k, v in ctx.args.options().items()
                  if k not in ("skip-email",)}
        if not fields:
            raise CliError("Need some fields to update.")
        changes = ", ".join(f"{k}={v}" for k, v in sorted(fields.items()))
        for target in ctx.args.positionals:
            ctx.out.success(f"Updated {noun} '{target}': {changes}.")
        return 0
    return handler


# --- site -----------------------------------------------------------------

def _site_create(ctx):
    args = ctx.args
    name = args.positional(0)
    if args.option("porcelain"):
        ctx.out.line(name)
        return 0
    visibility = "private" if args.option("private") else "public"
    title = args.option("title", name)
    ctx.out.success(f"Site '{name}' created (type: {args.option('type')}, "
                    f"title: {title}, visibility: {visibility}).")
    return 0


def _site_delete(ctx):
    name = ctx.args.positional(0)
    if not ctx.args.option("yes"):
        raise CliError(f"Refusing to delete site '{name}' without --yes.")
    tables = " Tables were kept." if ctx.args.option("keep-tables") else ""
    ctx.out.success(f"Site '{name}' deleted.{tables}")
    return 0


def _site_empty(ctx):
    name = ctx.args.positional(0)
    if not ctx.args.option("yes"):
        raise CliError(f"Refusing to empty site '{name}' without --yes.")
    ctx.out.success(f"Site '{name}' emptied.")
    return 0


def _site_list(ctx):
    return _render(ctx, list(_SITES), ["name", "type", "title", "status"])


# --- user -----------------------------------------------------------------

def _user_create(ctx):
    args = ctx.args
    if args.option("porcelain"):
        ctx.out.line("3")
        return 0
    ctx.out.success(f"Created user 3 '{args.positional(0)}' <{args.option('email')}> "
                    f"with role {args.option('role')}.")
    return 0


def _user_delete(ctx):
    if not ctx.args.option("yes"):
        raise CliError("Refusing to delete users without --yes.")
    reassign = ctx.args.option("reassign")
    for user in ctx.args.positionals:
        note = f" Posts reassigned to {reassign}." if reassign else ""
        ctx.out.success(f"Removed user '{user}'.{note}")
    return 0


def _user_get(ctx):
    user = ctx.args.positional(0)
    records = [u for u in _USERS if user in (str(u["ID"]), u["user_login"])]
    if not records:
        raise CliError(f"Invalid user ID, email or login: '{user}'")
    return _render(ctx, records, list(records[0]))


def _user_list(ctx):
    records = _filtered(_USERS, "roles", ctx.args.option("role"))
    return _render(ctx, records, ["ID", "user_login", "user_email", "roles"])


# --- registration ---------------------------------------------------------

_LIST_FORMAT = "[--field=<field>] [--fields=<fields>] [--format=<format>]"


def register_all(tree):
    """Register every built-in command on ``tree``."""
    r = tree.register

    r("cache", description="Adds, removes, fetches, and flushes the object cache.")
    r("cache add", _cache_set("Added"), synopsis="<key> <value> [<group>] [<expiration>]",
      description="Adds a value to the object cache.",
      defaults={"group": "default", "expiration": "0"})
    r("cache decr", _cache_step(-1), synopsis="<key> [<offset>] [<group>]",
      description="Decrements a value in the object cache.",
      defaults={"offset": "1", "group": "default"})
    r("cache delete", _cache_delete, synopsis="<key> [<group>]",
      description="Removes a value from the object cache.", defaults={"group": "default"})
    r("cache flush", _cache_flush, description="Flushes the object cache.")
    r("cache get", _cache_get, synopsis="<key> [<group>]",
      description="Gets a value from the object cache.", defaults={"group": "default"})
    r("cache incr", _cache_step(1), synopsis="<key> [<offset>] [<group>]",
      description="Increments a value in the object cache.",
      defaults={"offset": "1", "group": "default"})
    r("cache set", _cache_set("Set"), synopsis="<key> <value> [<group>] [<expiration>]",
      description="Sets a value to the object cache, regardless of whether it already exists.",
      defaults={"group": "default", "expiration": "0"})

    r("cli", description="Reviews current appctl info and checks registered commands.")
    r("cli alias", description="Retrieves aliases.")
    r("cli alias get", _cli_alias_get, synopsis="<key>",
      description="Gets the value for an alias.")
    r("cli alias list", _cli_alias_list, synopsis="[--format=<format>]",
      description="Lists available aliases.", defaults={"format": "yaml"})
    r("cli has-command", _cli_has_command, synopsis="<command-name>...",
      description="Detects if a command exists.")
    r("cli info", _cli_info, synopsis="[--format=<format>]",
      description="Prints various details about the appctl environment.",
      defaults={"format": "list"})
    r("cli param-dump", _cli_param_dump, synopsis="[--with-values] [--format=<format>]",
      description="Dumps the list of global parameters.", defaults={"format": "json"})
    r("cli version", _cli_version, description="Prints appctl version.")

    r("config", alias="cfg", description="Generates and reads the configuration file.")
    r("config delete", _config_delete, synopsis="<name> [--type=<type>]",
      description="Deletes a specific constant or variable from the config file.",
      defaults={"type": "all"})
    r("config get", _config_get, synopsis="<name> [--type=<type>]",
      description="Gets the value of a specific constant or variable defined in the config file.",
      defaults={"type": "all"})
    r("config list", _config_list, synopsis=f"[<filter>...] {_LIST_FORMAT} [--strict]",
      description="Lists variables, constants, and file includes defined in the config file.",
      defaults={"format": "table"})
    r("config set", _config_set,
      synopsis="<name> <value> [--add] [--[no-]raw] [--anchor=<anchor>] [--type=<type>]",
      description="Sets the value of a specific constant or variable defined in the config file.",
      defaults={"type": "constant"})

    r("help", _help, synopsis="[<command>...] [--<field>=<value>]",
      description="Gets help for appctl commands.")

    r("option", description="Retrieves and sets site options.")
    r("option add", _option_write("Added"),
      synopsis="<key> [<value>] [--format=<format>] [--autoload=<autoload>]",
      description="Adds a new option value.", defaults={"autoload": "yes", "format": "plaintext"})
    r("option delete", _each_factory("Deleted", "option"), synopsis="<key>...",
      description="Deletes an option.")
    r("option get", _option_get, synopsis="<key> [--format=<format>]",
      description="Gets the value for an option.", defaults={"format": "var_export"})
    r("option list", _option_list,
      synopsis=f"[--search=<pattern>] [--exclude=<pattern>] [--autoload=<value>] {_LIST_FORMAT}",
      description="Lists options and their values.", defaults={"format": "table"})
    r("option update", _option_write("Updated"),
      synopsis="<key> [<value>] [--autoload=<autoload>] [--format=<format>]",
      description="Updates an option value.", defaults={"autoload": "yes", "format": "plaintext"})

    r("plugin", description="Manages plugins, including installs, activations, and updates.")
    r("plugin activate", _plugin_bulk("activated"), synopsis="[<plugin>...] [--all] [--network]",
      description="Activates one or more plugins.")
    r("plugin deactivate", _plugin_bulk("deactivated"),
      synopsis="[<plugin>...] [--uninstall] [--all] [--network]",
      description="Deactivates one or more plugins.")
    r("plugin delete", _plugin_bulk("deleted"), synopsis="[<plugin>...] [--all]",
      description="Deletes plugin files without deactivating or uninstalling.")
    r("plugin install", _plugin_install,
      synopsis="<plugin|zip|url>... [--version=<version>] [--force] [--activate]",
      description="Installs one or more plugins.")
    r("plugin list", _plugin_list, synopsis=f"[--status=<status>] {_LIST_FORMAT}",
      description="Gets a list of plugins.", defaults={"format": "table"})
    r("plugin uninstall", _plugin_bulk("uninstalled"),
      synopsis="[<plugin>...] [--deactivate] [--skip-delete] [--all]",
      description="Uninstalls one or more plugins.")

    r("post", description="Manages posts, content, and meta.")
    r("post create", _post_create,
      synopsis="[--title=<title>] [--content=<content>] [--status=<status>] "
               "[--type=<type>] [--porcelain]",
      description="Creates a new post.", defaults={"status": "draft", "type": "post"})
    r("post delete", _each_factory("Deleted", "post"), synopsis="<id>... [--force]",
      description="Deletes an existing post.")
    r("post get", _post_get, synopsis=f"<id> {_LIST_FORMAT}",
      description="Gets details about a post.", defaults={"format": "table"})
    r("post list", _post_list, synopsis=f"[--<field>=<value>] {_LIST_FORMAT}",
      description="Gets a list of posts.", defaults={"format": "table"})
    r("post update", _update_fields("post"), synopsis="<id>... [--<field>=<value>]",
      description="Updates one or more existing posts.")

    r("site", description="Creates, deletes, empties, archives, and lists sites.")
    r("site archive", _each_factory("Archived", "site"), synopsis="<site-name>...",
      description="Archives one or more sites.")
    r("site create", _site_create, alias="new",
      synopsis="<site-name> [--type=<type>] [--title=<title>] [--email=<email>] "
               "[--private] [--porcelain]",
      description="Creates a site.", defaults={"type": "standard"})
    r("site delete", _site_delete, alias="rm",
      synopsis="<site-name> [--yes] [--keep-tables]",
      description="Deletes a site.")
    r("site empty", _site_empty, synopsis="<site-name> [--uploads] [--yes]",
      description="Empties a site of its content.")
    r("site list", _site_list, alias="ls", synopsis=_LIST_FORMAT,
      description="Lists all sites.", defaults={"format": "table"})
    r("site update", _update_fields("site"), synopsis="<site-name> [--<field>=<value>]",
      description="Updates fields of a site.")

    r("user", description="Manages users, along with their roles and meta.")
    r("user create", _user_create,
      synopsis="<user-login> --email=<email> [--role=<role>] "
               "[--display-name=<name>] [--send-email] [--porcelain]",
      description="Creates a new user.", defaults={"role": "subscriber"})
    r("user delete", _user_delete, synopsis="<user>... [--reassign=<user-id>] [--yes]",
      description="Deletes one or more users.")
    r("user get", _user_get, synopsis=f"<user> {_LIST_FORMAT}",
      description="Gets details about a user.", defaults={"format": "table"})
    r("user list", _user_list, synopsis=f"[--role=<role>] {_LIST_FORMAT}",
      description="Lists users.", defaults={"format": "table"})
    r("user update", _update_fields("user"),
      synopsis="<user>... [--<field>=<value>] [--skip-email]",
      description="Updates an existing user.")


def _each_factory(verb, noun):
    return lambda ctx: _each(ctx, verb, noun)
