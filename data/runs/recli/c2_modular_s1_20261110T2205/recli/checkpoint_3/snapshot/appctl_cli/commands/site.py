"""``appctl site``: site management (simulated)."""

import re

from ..errors import AppctlError
from ._listing import LIST_OPTIONS, confirm, render_list

SITES = [
    {"name": "blog", "type": "blog", "url": "https://blog.example.test", "status": "active"},
    {"name": "main", "type": "standard", "url": "https://main.example.test", "status": "active"},
    {"name": "shop", "type": "store", "url": "https://shop.example.test", "status": "archived"},
]
FIELDS = ["name", "type", "url", "status"]
SITE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _find(name):
    return next((s for s in SITES if s["name"] == name), None)


def create(ctx, args, assoc):
    name = args[0]
    if not SITE_NAME_RE.match(name):
        raise AppctlError(
            f"Invalid site name '{name}'. Use lowercase letters, numbers and hyphens only."
        )
    if _find(name):
        raise AppctlError(f"Site '{name}' already exists.")
    if assoc.get("porcelain"):
        ctx.output.line(name)
        return
    title = assoc.get("title") or name
    visibility = "private" if assoc.get("private") else "public"
    ctx.output.success(
        f"Site '{name}' created (type: {assoc['type']}, title: {title}, "
        f"email: {assoc['email']}, visibility: {visibility})."
    )


def delete(ctx, args, assoc):
    name = args[0]
    if _find(name) is None:
        raise AppctlError(f"Site '{name}' does not exist.")
    if not confirm(ctx, assoc, f"Are you sure you want to delete the '{name}' site?"):
        return
    suffix = " Database tables were kept." if assoc.get("keep-tables") else ""
    ctx.output.success(f"The site '{name}' was deleted.{suffix}")


def list_(ctx, args, assoc):
    render_list(ctx, SITES, assoc, FIELDS, id_field="name")


def _set_status(status):
    def handler(ctx, args, assoc):
        failed = 0
        for name in args:
            site = _find(name)
            if site is None:
                ctx.output.warning(f"Site '{name}' does not exist.")
                failed += 1
            elif site["status"] == status:
                ctx.output.warning(f"Site '{name}' is already {status}.")
            else:
                ctx.output.success(f"Site '{name}' {status}.")
        return 1 if failed else 0
    return handler


def empty(ctx, args, assoc):
    if not confirm(ctx, assoc, "Are you sure you want to empty the site of all content?"):
        return
    extra = " Uploaded files were removed." if assoc.get("uploads") else ""
    ctx.output.success(f"The site was emptied.{extra}")


def register(registry):
    registry.add("site", description="Creates, deletes, empties, and lists sites.")
    site_option = {"site-name": "The name of the site."}
    registry.add(
        "site activate", _set_status("active"),
        synopsis="<site-name>...",
        description="Activates one or more sites.",
        options=site_option,
    )
    registry.add(
        "site archive", _set_status("archived"),
        synopsis="<site-name>...",
        description="Archives one or more sites.",
        options=site_option,
    )
    registry.add(
        "site create", create,
        synopsis="<site-name> [--type=<type>] [--title=<title>] [--email=<email>] "
                 "[--[no-]private] [--porcelain]",
        description="Creates a site.",
        defaults={"type": "standard", "email": "admin@example.test", "private": False},
        options=dict(site_option, type="The type of site to create.",
                     title="Title of the new site. Defaults to the site name.",
                     email="Email for the site admin.",
                     private="If set, the new site will be non-public.",
                     porcelain="If set, only the site name will be output on success."),
    )
    registry.add(
        "site delete", delete,
        synopsis="<site-name> [--yes] [--keep-tables]",
        description="Deletes a site.",
        options=dict(site_option, yes="Answer yes to the confirmation message.",
                     **{"keep-tables": "Delete the site but keep its database tables."}),
    )
    registry.add(
        "site empty", empty,
        synopsis="[--uploads] [--yes]",
        description="Empties a site of its content.",
        options={"uploads": "Also delete uploaded files.",
                 "yes": "Answer yes to the confirmation message."},
    )
    registry.add(
        "site list", list_,
        synopsis="[--<field>=<value>] [--field=<field>] [--fields=<fields>] [--format=<format>]",
        description="Lists all sites.",
        alias="ls",
        defaults={"format": "table"},
        options=LIST_OPTIONS,
    )
