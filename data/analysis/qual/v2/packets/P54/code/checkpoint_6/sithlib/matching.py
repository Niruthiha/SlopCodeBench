"""Query matching.

Secret: the algorithm deciding whether a typed query matches a candidate
name (prefix, or in-order subsequence when fuzzy; ignoring case unless asked
not to) and how much of the name remains to be inserted.
"""


def matches(name, query, fuzzy=False, case_sensitive=False):
    if not query:
        return True
    if not case_sensitive:
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
