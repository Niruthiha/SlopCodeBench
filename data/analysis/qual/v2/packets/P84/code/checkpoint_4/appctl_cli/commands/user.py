"""``appctl user``: user and user-meta management (simulated)."""

from ..errors import AppctlError
from ..formatter import format_value
from ._listing import LIST_OPTIONS, render_list, render_record

USERS = [
    {"ID": 1, "user_login": "admin", "user_email": "admin@example.test",
     "display_name": "Administrator", "roles": "administrator"},
    {"ID": 2, "user_login": "editor", "user_email": "editor@example.test",
     "display_name": "Edith Editor", "roles": "editor"},
    {"ID": 3, "user_login": "author", "user_email": "author@example.test",
     "display_name": "Arthur Author", "roles": "author"},
]
FIELDS = ["ID", "user_login", "user_email", "display_name", "roles"]
PREFIX = "user"
META = {1: {"nickname": "admin", "locale": "en_US"}, 2: {"nickname": "editor"}, 3: {}}
ROLES = ("administrator", "editor", "author", "contributor", "subscriber")


def find_user(identifier):
    """Look a user up by ID, login or email."""
    for user in USERS:
        if identifier in (str(user["ID"]), user["user_login"], user["user_email"]):
            return user
    return None


def require_user(identifier):
    user = find_user(identifier)
    if user is None:
        raise AppctlError(f"Invalid user ID, email or login: '{identifier}'")
    return user


def _check_role(role):
    if role not in ROLES:
        raise AppctlError(f"Role doesn't exist: {role}")


def create(ctx, args, assoc):
    login, email = args
    if find_user(login) or find_user(email):
        raise AppctlError(f"Sorry, that username or email address already exists: {login}")
    _check_role(assoc["role"])
    new_id = max(u["ID"] for u in USERS) + 1
    if assoc.get("porcelain"):
        ctx.output.line(str(new_id))
        return
    ctx.output.success(f"Created user {new_id} ({login}, role: {assoc['role']}).")
    if not assoc.get("user_pass"):
        ctx.output.line("Password: (generated)")


def delete(ctx, args, assoc):
    reassign = assoc.get("reassign")
    if reassign:
        require_user(reassign)
    for identifier in args:
        user = require_user(identifier)
        suffix = f" and reassigned posts to user {reassign}" if reassign else ""
        scope = " from the network" if assoc.get("network") else ""
        ctx.output.success(f"Removed user {user['ID']}{scope}{suffix}.")


def get(ctx, args, assoc):
    render_record(ctx, require_user(args[0]), assoc, FIELDS, prefix=PREFIX)


def list_(ctx, args, assoc):
    filters = dict(assoc)
    role = filters.pop("role", None)
    if role:
        filters["roles"] = role
    render_list(ctx, USERS, filters, FIELDS, id_field="ID", prefix=PREFIX)


def update(ctx, args, assoc):
    for identifier in args:
        user = require_user(identifier)
        ctx.output.success(f"Updated user {user['ID']}.")


def set_role(ctx, args, assoc):
    user = require_user(args[0])
    role = args[1]
    _check_role(role)
    ctx.output.success(f"Added {user['user_login']} ({user['ID']}) to {role} role.")


# -- user meta -----------------------------------------------------------

def meta_add(ctx, args, assoc):
    user = require_user(args[0])
    ctx.output.success(f"Added custom field '{args[1]}' for user {user['ID']}.")


def meta_delete(ctx, args, assoc):
    user = require_user(args[0])
    if args[1] not in META.get(user["ID"], {}):
        raise AppctlError(f"Failed to delete custom field '{args[1]}'.")
    ctx.output.success(f"Deleted custom field '{args[1]}'.")


def meta_get(ctx, args, assoc):
    user = require_user(args[0])
    meta = META.get(user["ID"], {})
    if args[1] not in meta:
        return 1
    ctx.output.line(format_value(meta[args[1]], assoc["format"]))


def meta_list(ctx, args, assoc):
    user = require_user(args[0])
    items = [{"user_id": user["ID"], "meta_key": k, "meta_value": v}
             for k, v in sorted(META.get(user["ID"], {}).items())]
    keys = assoc.get("keys")
    if keys and keys is not True:
        wanted = set(keys.split(","))
        items = [i for i in items if i["meta_key"] in wanted]
    filters = {k: v for k, v in assoc.items() if k != "keys"}
    render_list(ctx, items, filters, ["user_id", "meta_key", "meta_value"], id_field="meta_key")


def meta_update(ctx, args, assoc):
    user = require_user(args[0])
    current = META.get(user["ID"], {}).get(args[1])
    if current == args[2]:
        ctx.output.success("Value passed for custom field '{}' is unchanged.".format(args[1]))
    else:
        ctx.output.success(f"Updated custom field '{args[1]}'.")


def register(registry):
    registry.add("user", description="Manages users, along with their roles, capabilities, and meta.")
    user_option = {"user": "User ID, user email, or user login."}
    registry.add(
        "user create", create,
        synopsis="<user-login> <user-email> [--role=<role>] [--user_pass=<password>] "
                 "[--display_name=<name>] [--send-email] [--porcelain]",
        description="Creates a new user.",
        defaults={"role": "subscriber"},
        options={"user-login": "The login of the user to create.",
                 "user-email": "The email address of the user to create.",
                 "role": "The role of the user to create.",
                 "user_pass": "The user password.",
                 "display_name": "The display name.",
                 "send-email": "Send an email to the user with their new account details.",
                 "porcelain": "Output just the new user id."},
    )
    registry.add(
        "user delete", delete,
        synopsis="<user>... [--network] [--reassign=<user-id>]",
        description="Deletes one or more users.",
        alias="remove",
        options=dict(user_option, network="Remove the user from the entire network.",
                     reassign="User ID to reassign the posts to."),
    )
    registry.add(
        "user get", get,
        synopsis="<user> [--field=<field>] [--fields=<fields>] [--format=<format>]",
        description="Gets details about a user.",
        defaults={"format": "table"},
        options=dict(LIST_OPTIONS, **user_option),
    )
    registry.add(
        "user list", list_,
        synopsis="[--role=<role>] [--<field>=<value>] [--field=<field>] "
                 "[--fields=<fields>] [--format=<format>]",
        description="Lists users.",
        defaults={"format": "table"},
        options=dict(LIST_OPTIONS, role="Only display users with a certain role."),
    )
    registry.add("user meta", description="Adds, updates, deletes, and lists user custom fields.")
    meta_options = dict(user_option, key="The name of the meta field.",
                        value="The value of the meta field.",
                        format="The serialization format for the value (plaintext, json).")
    registry.add(
        "user meta add", meta_add,
        synopsis="<user> <key> <value> [--format=<format>]",
        description="Adds a meta field.",
        defaults={"format": "plaintext"}, options=meta_options,
    )
    registry.add(
        "user meta delete", meta_delete,
        synopsis="<user> <key> [<value>]",
        description="Deletes a meta field.",
        options=meta_options,
    )
    registry.add(
        "user meta get", meta_get,
        synopsis="<user> <key> [--format=<format>]",
        description="Gets meta field value.",
        defaults={"format": "plaintext"}, options=meta_options,
    )
    registry.add(
        "user meta list", meta_list,
        synopsis="<user> [--keys=<keys>] [--fields=<fields>] [--format=<format>]",
        description="Lists all metadata associated with a user.",
        defaults={"format": "table"},
        options=dict(LIST_OPTIONS, keys="Limit output to metadata of specific keys.", **user_option),
    )
    registry.add(
        "user meta update", meta_update,
        synopsis="<user> <key> <value> [--format=<format>]",
        description="Updates a meta field.",
        alias="set",
        defaults={"format": "plaintext"}, options=meta_options,
    )
    registry.add(
        "user set-role", set_role,
        synopsis="<user> [<role>]",
        description="Sets the user role.",
        defaults={"role": "subscriber"},
        options=dict(user_option, role="Make the user have the specified role."),
    )
    registry.add(
        "user update", update,
        synopsis="<user>... [--user_pass=<password>] [--display_name=<name>] "
                 "[--<field>=<value>] [--skip-email]",
        description="Updates an existing user.",
        options=dict(user_option, user_pass="A string that contains the plain text password for the user.",
                     display_name="A string that will be shown on the site.",
                     **{"skip-email": "Don't send an email notification to the user."}),
    )
