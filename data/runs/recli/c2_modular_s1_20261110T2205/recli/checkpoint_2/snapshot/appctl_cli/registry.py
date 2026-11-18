"""Registration of commands into a tree rooted at the program command."""

from . import PROGRAM_NAME
from .command import Command


class CommandRegistry:
    """Builds the command tree from multi-level command paths."""

    def __init__(self, description=""):
        self.root = Command(PROGRAM_NAME, description=description)

    def add(self, path, handler=None, **attributes):
        """Register ``path`` (e.g. ``"site create"``) and return the command.

        Parent commands must be registered before their subcommands.
        """
        parts = path.split()
        if not parts:
            raise ValueError("A command path cannot be empty")
        parent = self.root
        for index, part in enumerate(parts[:-1]):
            child = parent.subcommands.get(part)
            if child is None:
                missing = " ".join(parts[: index + 1])
                raise ValueError(f"Parent command '{missing}' must be registered before '{path}'")
            parent = child
        return parent.add_subcommand(Command(parts[-1], handler=handler, **attributes))

    def get(self, path):
        node = self.root
        for part in path.split():
            node = node.subcommands[part]
        return node
