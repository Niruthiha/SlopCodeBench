"""Completion ordering.

Secret: the ranking rules — public names, then private, then dunder names,
then keywords, each group alphabetical ignoring case.
"""


def _group(name, is_keyword):
    if is_keyword:
        return 3
    if name.startswith("__") and name.endswith("__"):
        return 2
    if name.startswith("_"):
        return 1
    return 0


def rank(items, name_of, is_keyword):
    """Return ``items`` sorted; ``name_of``/``is_keyword`` describe an item."""
    return sorted(items, key=lambda item: (_group(name_of(item), is_keyword(item)),
                                           name_of(item).lower(), name_of(item)))
