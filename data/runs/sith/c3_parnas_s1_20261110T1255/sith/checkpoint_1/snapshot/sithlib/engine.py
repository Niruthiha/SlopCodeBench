"""Completion engine.

Secret: the completion policy — which candidates each cursor context offers
(visible names plus keywords, or public module members, or receiver
attributes) and how filtering, wording and ranking are combined.
"""

from . import cursor, matching, presentation, ranking, vocabulary
from .inference import MODULE, Project
from .source import SourceFile


def complete(path, line, col, fuzzy=False):
    """Return completions as a list of (name, complete, type, description)."""
    source = SourceFile(path)
    source.check_position(line, col)
    context = cursor.analyze(source.text_before(line, col))
    if context.kind == cursor.NONE:
        return []

    location = Project(source.path, source.text()).location(line, col)
    keywords = []
    if context.kind == cursor.NAME:
        entities = location.visible_entities()
        keywords = vocabulary.keywords()
    else:
        receiver = location.evaluate(context.receiver)
        entities = receiver.members()
        if receiver.kind == MODULE:
            entities = {n: e for n, e in entities.items() if not n.startswith("_")}

    query = context.prefix
    results = []
    for name, entity in entities.items():
        if matching.matches(name, query, fuzzy):
            kind, type_name = entity.presentation()
            results.append((name, False) + presentation.describe(name, kind, type_name))
    for word in keywords:
        if word not in entities and matching.matches(word, query, fuzzy):
            results.append((word, True) + presentation.describe(word, presentation.KEYWORD))

    ordered = ranking.rank(results, name_of=lambda r: r[0], is_keyword=lambda r: r[1])
    return [(name, matching.remaining_text(name, query), kind, description)
            for name, _, kind, description in ordered]
