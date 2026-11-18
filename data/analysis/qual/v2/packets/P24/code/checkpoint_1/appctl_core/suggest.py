"""Similarity-based suggestions.

Secret: the distance metric (case-insensitive Levenshtein), the acceptance threshold, the
tie-breaking order and the precedence of curated synonyms used to pick a
single deterministic "Did you mean" candidate.
"""

from . import synonyms as _synonyms

_THRESHOLD = 2


def _distance(a, b):
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (char_a != char_b),
            ))
        previous = current
    return previous[-1]


def suggest(target, candidates):
    """Return the best candidate for a mistyped ``target``, or ``None``."""
    pool = sorted(set(candidates), key=lambda c: (c.casefold(), c))
    if not pool:
        return None
    synonym = _synonyms.synonym_for(target)
    if synonym is not None and synonym in pool:
        return synonym
    folded = target.casefold()
    best = min(pool, key=lambda c: _distance(folded, c.casefold()))
    if best != target and _distance(folded, best.casefold()) <= _THRESHOLD:
        return best
    return None
