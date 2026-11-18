"""Prefix and fuzzy matching of completion names."""


def prefix_match(prefix, name, case_insensitive=True):
    if case_insensitive:
        return name.lower().startswith(prefix.lower())
    return name.startswith(prefix)


def fuzzy_match(query, name, case_insensitive=True):
    """True when the characters of `query` appear in `name` in order."""
    if case_insensitive:
        query, name = query.lower(), name.lower()
    remaining = iter(name)
    return all(char in remaining for char in query)


def make_matcher(prefix, fuzzy, case_insensitive=True):
    if not prefix:
        return lambda name: True
    if fuzzy:
        return lambda name: fuzzy_match(prefix, name, case_insensitive)
    return lambda name: prefix_match(prefix, name, case_insensitive)
