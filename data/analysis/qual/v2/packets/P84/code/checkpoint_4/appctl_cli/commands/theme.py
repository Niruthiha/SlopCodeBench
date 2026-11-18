"""``appctl theme``: theme management (simulated)."""

from ..errors import AppctlError
from ._extensions import ExtensionCatalog
from ._listing import LIST_OPTIONS

CATALOG = ExtensionCatalog("theme", [
    {"name": "astra", "title": "Astra", "status": "inactive", "update": "available", "version": "4.6.4"},
    {"name": "twentytwentyfour", "title": "Twenty Twenty-Four", "status": "active", "update": "none", "version": "1.1"},
    {"name": "twentytwentythree", "title": "Twenty Twenty-Three", "status": "inactive", "update": "none", "version": "1.4"},
])


def activate(ctx, args, assoc):
    theme = CATALOG.find(args[0])
    if theme is None:
        raise AppctlError(f"The '{args[0]}' theme could not be found.")
    if theme["status"] == "active":
        ctx.output.warning(f"The '{theme['title']}' theme is already active.")
        return
    ctx.output.success(f"Switched to '{theme['title']}' theme.")


def register(registry):
    registry.add("theme", description="Manages themes, including installs, activations, and updates.")
    theme_options = {"theme": "One or more themes.", "all": "If set, all themes will be targeted."}
    registry.add(
        "theme activate", activate,
        synopsis="<theme>",
        description="Activates a theme.",
        options={"theme": "The theme to activate."},
    )
    registry.add(
        "theme delete", CATALOG.delete,
        synopsis="[<theme>...] [--all] [--force]",
        description="Deletes one or more themes.",
        options=dict(theme_options, force="To delete active theme use this."),
    )
    registry.add(
        "theme install", CATALOG.install,
        synopsis="<theme|zip|url>... [--version=<version>] [--force] [--activate]",
        description="Installs one or more themes.",
        defaults={"version": "latest"},
        options={"version": "Get a particular version from the repository.",
                 "force": "If set, the command will overwrite any installed version of the theme.",
                 "activate": "If set, the theme will be activated immediately after install."},
    )
    registry.add(
        "theme list", CATALOG.list,
        synopsis="[--<field>=<value>] [--field=<field>] [--fields=<fields>] [--format=<format>]",
        description="Gets a list of themes.",
        defaults={"format": "table"},
        options=LIST_OPTIONS,
    )
    registry.add(
        "theme status", CATALOG.status,
        synopsis="[<theme>]",
        description="Reveals the status of one or all themes.",
    )
    registry.add(
        "theme update", CATALOG.update,
        synopsis="[<theme>...] [--all] [--dry-run]",
        description="Updates one or more themes.",
        options=dict(theme_options, **{"dry-run": "Preview which themes would be updated."}),
    )
