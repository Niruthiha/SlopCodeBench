"""Ordering of completion results."""


def name_group(name):
    """0 for public names, 1 for private (`_x`), 2 for dunders (`__x__`)."""
    if name.startswith("__") and name.endswith("__"):
        return 2
    if name.startswith("_"):
        return 1
    return 0


def sort_names(names):
    return sorted(names, key=lambda name: (name_group(name), name.lower(), name))


def sort_keywords(keywords):
    return sorted(keywords, key=lambda name: (name.lower(), name))
