"""Prefix and fuzzy matching of completion names."""


def prefix_match(prefix, name):
    return name.lower().startswith(prefix.lower())


def fuzzy_match(query, name):
    """True when the characters of `query` appear in `name` in order."""
    remaining = iter(name.lower())
    return all(char in remaining for char in query.lower())


def make_matcher(prefix, fuzzy):
    if not prefix:
        return lambda name: True
    if fuzzy:
        return lambda name: fuzzy_match(prefix, name)
    return lambda name: prefix_match(prefix, name)
