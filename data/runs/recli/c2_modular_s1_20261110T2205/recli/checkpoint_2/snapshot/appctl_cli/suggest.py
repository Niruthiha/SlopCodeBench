"""Deterministic "Did you mean?" suggestions."""

DEFAULT_THRESHOLD = 2

# Curated synonyms for common command-name variants. A synonym is only
# suggested when its target is one of the registered options.
SYNONYMS = {
    "add": "create",
    "check": "check-update",
    "capability": "cap",
    "clear": "flush",
    "decrement": "decr",
    "del": "delete",
    "directory": "dir",
    "exec": "eval",
    "exec-file": "eval-file",
    "increment": "incr",
    "language": "locale",
    "lang": "locale",
    "new": "create",
    "number": "count",
    "remove": "delete",
    "regen": "regenerate",
    "rep": "replace",
    "repl": "replace",
    "rm": "delete",
    "trash": "delete",
    "v": "version",
}


def levenshtein(source, target):
    """Return the edit distance between two strings."""
    if source == target:
        return 0
    if not source:
        return len(target)
    if not target:
        return len(source)
    previous = list(range(len(target) + 1))
    for i, s_char in enumerate(source, start=1):
        current = [i]
        for j, t_char in enumerate(target, start=1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (s_char != t_char),
            ))
        previous = current
    return previous[-1]


def get_suggestion(target, options, threshold=DEFAULT_THRESHOLD):
    """Return the closest option to ``target`` or ``None``.

    Synonyms win over edit distance. A match must be within ``threshold``
    edits and must not replace every character of ``target``. Ties are
    broken alphabetically (case-insensitively) so the result is stable.
    """
    candidates = sorted(set(options), key=lambda o: (o.lower(), o))
    if not candidates:
        return None

    synonym = SYNONYMS.get(target)
    if synonym is not None and synonym in candidates:
        return synonym

    best_distance, best = None, None
    for option in candidates:
        distance = levenshtein(target, option)
        if best_distance is None or distance < best_distance:
            best_distance, best = distance, option

    if best_distance <= threshold and best_distance < len(target) and best != target:
        return best
    return None
