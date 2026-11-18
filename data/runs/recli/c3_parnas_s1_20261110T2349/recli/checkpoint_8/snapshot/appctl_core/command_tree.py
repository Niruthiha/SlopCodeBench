"""Command storage.

Secret: how commands are stored as a tree, how names and aliases are
matched, and how children are ordered for display.
"""

from .synopsis import Synopsis


def _sort_key(name):
    return (name.casefold(), name)


class CommandNode:
    """One command (or the root) in the command tree."""

    def __init__(self, name, parent=None):
        self._name = name
        self._parent = parent
        self._children = {}
        self._aliases = {}
        self._handler = None
        self._synopsis_text = ""
        self._synopsis = Synopsis("")
        self._description = ""
        self._alias = None
        self._defaults = {}
        self._longdesc = ""

    def _configure(self, handler, synopsis, description, alias, defaults, longdesc=""):
        self._handler = handler
        self._synopsis_text = synopsis or ""
        self._synopsis = Synopsis(self._synopsis_text)
        self._description = description or ""
        self._alias = alias
        self._defaults = dict(defaults or {})
        self._longdesc = longdesc or ""

    @property
    def name(self):
        return self._name

    @property
    def path(self):
        """Full space-separated command path ('' for the root)."""
        words = []
        node = self
        while node._parent is not None:
            words.append(node._name)
            node = node._parent
        return " ".join(reversed(words))

    @property
    def parent(self):
        return self._parent

    @property
    def description(self):
        return self._description

    @property
    def longdesc(self):
        return self._longdesc

    @property
    def alias(self):
        return self._alias

    @property
    def synopsis(self):
        return self._synopsis

    def defaults(self):
        return dict(self._defaults)

    def is_root(self):
        return self._parent is None

    def is_runnable(self):
        return self._handler is not None

    def has_children(self):
        return bool(self._children)

    def children(self):
        return [self._children[n] for n in sorted(self._children, key=_sort_key)]

    def child_names(self):
        return sorted(self._children, key=_sort_key)

    def find_child(self, word):
        """Match ``word`` against child names, then child aliases."""
        if word in self._children:
            return self._children[word]
        canonical = self._aliases.get(word)
        return self._children.get(canonical) if canonical else None

    def run(self, context):
        return self._handler(context)

    def _child(self, name, create):
        if name not in self._children and create:
            if name in self._aliases:
                raise ValueError(f"'{name}' is already an alias under '{self.path}'")
            self._children[name] = CommandNode(name, self)
        return self._children.get(name)

    def _add_alias(self, alias, canonical):
        if alias in self._children or self._aliases.get(alias, canonical) != canonical:
            raise ValueError(f"alias '{alias}' conflicts under '{self.path}'")
        self._aliases[alias] = canonical


class CommandTree:
    """Registry of all commands."""

    def __init__(self):
        self._root = CommandNode("")

    @property
    def root(self):
        return self._root

    def register(self, path, handler=None, *, synopsis="", description="",
                 alias=None, defaults=None, longdesc=""):
        """Register (or update) the command at space-separated ``path``.

        Missing parent commands are created as non-runnable groups.
        """
        words = path.split()
        if not words:
            raise ValueError("command path must not be empty")
        node = self._root
        for word in words:
            node = node._child(word, create=True)
        node._configure(handler, synopsis, description, alias, defaults, longdesc)
        if alias:
            node.parent._add_alias(alias, node.name)
        return node

    def find(self, words):
        """Return the node at exactly ``words`` (aliases allowed) or ``None``."""
        node = self._root
        for word in words:
            node = node.find_child(word)
            if node is None:
                return None
        return None if node is self._root else node
