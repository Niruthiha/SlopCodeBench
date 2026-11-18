"""Assembly of the full appctl command tree."""

from ..registry import CommandRegistry
from . import cache, cli, config, db, help, option, plugin, post, site, theme, user

COMMAND_MODULES = (cache, cli, config, db, help, option, plugin, post, site, theme, user)


def build_command_tree():
    registry = CommandRegistry(description="Manage applications from the command line.")
    for module in COMMAND_MODULES:
        module.register(registry)
    return registry.root
