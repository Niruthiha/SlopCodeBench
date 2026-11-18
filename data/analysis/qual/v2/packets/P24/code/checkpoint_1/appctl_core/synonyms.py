"""Curated synonym table.

Secret: which common command-name variants map to which canonical names.
"""

_SYNONYMS = {
    "add": "create",
    "new": "create",
    "make": "create",
    "check": "check-update",
    "clear": "flush",
    "purge": "flush",
    "decrement": "decr",
    "increment": "incr",
    "del": "delete",
    "remove": "delete",
    "rm": "delete",
    "trash": "delete",
    "ls": "list",
    "show": "get",
    "fetch": "get",
    "edit": "update",
    "modify": "update",
    "ver": "version",
    "v": "version",
}


def synonym_for(word):
    """Return the canonical name commonly meant by ``word``, or ``None``."""
    return _SYNONYMS.get(word)
