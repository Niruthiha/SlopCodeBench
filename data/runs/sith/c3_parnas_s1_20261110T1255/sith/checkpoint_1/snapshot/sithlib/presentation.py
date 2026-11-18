"""Completion wording.

Secret: the vocabulary used for a completion's ``type`` field and the
format of its human-readable ``description``.
"""

KEYWORD = "keyword"


def describe(name, kind, type_name=None):
    """Return ``(type, description)`` for a name of the given kind."""
    if kind == "module":
        return "module", "module %s" % name
    if kind == "class":
        return "class", "class %s" % name
    if kind == "function":
        return "function", "def %s(...)" % name
    if kind == "instance":
        return "instance", "instance of %s" % (type_name or "object")
    if kind == "param":
        return "param", "param %s" % name
    if kind == KEYWORD:
        return "keyword", name
    return "statement", "statement"
