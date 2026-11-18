"""``appctl plugin``: plugin management (simulated)."""

from ._extensions import ExtensionCatalog
from ._listing import LIST_OPTIONS

CATALOG = ExtensionCatalog("plugin", [
    {"name": "akismet", "title": "Akismet Anti-spam", "status": "active", "update": "none", "version": "5.3"},
    {"name": "hello-dolly", "title": "Hello Dolly", "status": "inactive", "update": "available", "version": "1.7.2"},
    {"name": "query-monitor", "title": "Query Monitor", "status": "active", "update": "none", "version": "3.15.0"},
])


def activate(ctx, args, assoc):
    names = CATALOG.targets(args, assoc)
    done = 0
    for name in CATALOG.each_installed(ctx, names):
        scope = " network wide" if assoc.get("network") else ""
        ctx.output.log(f"Plugin '{name}' activated{scope}.")
        done += 1
    CATALOG.summary(ctx, "Activated", done, len(names))


def deactivate(ctx, args, assoc):
    names = CATALOG.targets(args, assoc)
    done = 0
    for name in CATALOG.each_installed(ctx, names):
        ctx.output.log(f"Plugin '{name}' deactivated.")
        if assoc.get("uninstall"):
            ctx.output.log(f"Uninstalled '{name}' plugin.")
        done += 1
    CATALOG.summary(ctx, "Deactivated", done, len(names))


def register(registry):
    registry.add("plugin", description="Manages plugins, including installs, activations, and updates.")
    plugin_options = {"plugin": "One or more plugins.", "all": "If set, all plugins will be targeted."}
    registry.add(
        "plugin activate", activate,
        synopsis="[<plugin>...] [--all] [--network]",
        description="Activates one or more plugins.",
        options=dict(plugin_options, network="If set, the plugin will be activated for the entire network."),
    )
    registry.add(
        "plugin deactivate", deactivate,
        synopsis="[<plugin>...] [--uninstall] [--all]",
        description="Deactivates one or more plugins.",
        options=dict(plugin_options, uninstall="Uninstall the plugin after deactivation."),
    )
    registry.add(
        "plugin delete", CATALOG.delete,
        synopsis="[<plugin>...] [--all]",
        description="Deletes plugin files without deactivating or uninstalling.",
        options=plugin_options,
    )
    registry.add(
        "plugin install", CATALOG.install,
        synopsis="<plugin|zip|url>... [--version=<version>] [--force] [--activate]",
        description="Installs one or more plugins.",
        defaults={"version": "latest"},
        options={"version": "Get a particular version from the repository.",
                 "force": "If set, the command will overwrite any installed version of the plugin.",
                 "activate": "If set, the plugin will be activated immediately after install."},
    )
    registry.add(
        "plugin list", CATALOG.list,
        synopsis="[--<field>=<value>] [--field=<field>] [--fields=<fields>] [--format=<format>]",
        description="Gets a list of plugins.",
        defaults={"format": "table"},
        options=LIST_OPTIONS,
    )
    registry.add(
        "plugin status", CATALOG.status,
        synopsis="[<plugin>]",
        description="Reveals the status of one or all plugins.",
    )
    registry.add(
        "plugin update", CATALOG.update,
        synopsis="[<plugin>...] [--all] [--dry-run]",
        description="Updates one or more plugins.",
        options=dict(plugin_options, **{"dry-run": "Preview which plugins would be updated."}),
    )
