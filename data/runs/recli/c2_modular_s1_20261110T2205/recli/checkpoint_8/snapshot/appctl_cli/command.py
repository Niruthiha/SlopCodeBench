"""The command tree node."""

from .errors import SynopsisError
from .synopsis import invalid_tokens, parse_synopsis


def sort_key(name):
    """Case-insensitive alphabetical ordering with a stable tie-break."""
    return (name.lower(), name)


class Command:
    """A node in the command tree.

    A command may have a handler, subcommands, or both. A command with
    subcommands but no handler only prints its usage when invoked.
    """

    def __init__(self, name, description="", synopsis="", handler=None,
                 alias=None, defaults=None, options=None, longdesc="", machine_output=False):
        self.name = name
        self.description = description
        self.synopsis = " ".join((synopsis or "").split())
        self.handler = handler
        self.alias = alias
        self.defaults = dict(defaults or {})
        self.options = dict(options or {})
        self.longdesc = longdesc
        # The output is a machine-readable or shell-consumable payload.
        self.machine_output = bool(machine_output)
        self.parent = None
        self.subcommands = {}

        self.tokens = parse_synopsis(self.synopsis)
        bad = invalid_tokens(self.tokens)
        if bad:
            raise SynopsisError(
                f"The '{name}' command has an invalid synopsis part: {', '.join(bad)}"
            )

    # -- tree structure -------------------------------------------------

    def add_subcommand(self, command):
        for taken in self._taken_names():
            if taken in (command.name, command.alias):
                raise ValueError(
                    f"'{taken}' is already registered under '{self.full_name or 'appctl'}'"
                )
        command.parent = self
        self.subcommands[command.name] = command
        return command

    def _taken_names(self):
        for sub in self.subcommands.values():
            yield sub.name
            if sub.alias:
                yield sub.alias

    def find_subcommand(self, token):
        """Match a subcommand by canonical name first, then by alias."""
        if token in self.subcommands:
            return self.subcommands[token]
        for sub in self.subcommands.values():
            if sub.alias and sub.alias == token:
                return sub
        return None

    def sorted_subcommands(self):
        return [self.subcommands[k] for k in sorted(self.subcommands, key=sort_key)]

    def subcommand_names(self):
        return list(self.subcommands)

    # -- properties -----------------------------------------------------

    @property
    def is_root(self):
        return self.parent is None

    @property
    def has_subcommands(self):
        return bool(self.subcommands)

    @property
    def is_runnable(self):
        return self.handler is not None

    @property
    def path(self):
        """Canonical names from the top-level command down to this one."""
        parts = []
        node = self
        while node is not None and not node.is_root:
            parts.append(node.name)
            node = node.parent
        return list(reversed(parts))

    @property
    def full_name(self):
        return " ".join(self.path)

    def tokens_of_type(self, *types):
        return [t for t in self.tokens if t.type in types]

    def __repr__(self):
        return f"Command({self.full_name or '<root>'!r})"
