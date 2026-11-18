"""Query matching.

Secret: the algorithm deciding whether a typed query matches a candidate
name (case-insensitive prefix, or case-insensitive in-order subsequence when
fuzzy) and how much of the name remains to be inserted.
"""


def matches(name, query, fuzzy=False):
    if not query:
        return True
    name, query = name.lower(), query.lower()
    if not fuzzy:
        return name.startswith(query)
    position = 0
    for ch in query:
        position = name.find(ch, position)
        if position < 0:
            return False
        position += 1
    return True


def remaining_text(name, query):
    """Text to insert: the name minus as many characters as were typed."""
    return name[len(query):]
