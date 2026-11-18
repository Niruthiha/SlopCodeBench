"""Completion engine.

Secret: the completion policy — which candidates each cursor context offers
(visible names plus keywords, or public module members, or the attributes
of every possible receiver value, or importable modules, or the names a
module exports to ``from ... import``) and how filtering, wording and
ranking are combined (as the active settings ask: case sensitivity, and
whether an opening bracket follows function and class names).
"""

from . import config, cursor, matching, presentation, ranking, vocabulary
from .inference import MODULE, Project
from .source import SourceFile


def complete(path, line, col, fuzzy=False, root=None, namespaces=None):
    """Return completions as a list of (name, complete, type, description).
    ``namespaces``: interpreter namespaces supplying unresolved names."""
    source = SourceFile(path)
    source.check_position(line, col)
    context = cursor.analyze(source.text_before(line, col))
    if context.kind == cursor.NONE:
        return []

    text = source.lines()[line - 1]
    indent = len(text) - len(text.lstrip()) if text[:col].strip() else col
    project = Project(source.path, source.text(), root, namespaces)
    keywords = []
    if context.kind == cursor.IMPORT_MODULE:
        entities = project.module_names(context.module, context.level)
    elif context.kind == cursor.IMPORT_NAME:
        module = project.module_value(context.module, context.level)
        entities = project.importable_members(module) if module is not None else {}
    elif context.kind == cursor.KEYWORDS:
        entities = {}
        keywords = context.words
    elif context.kind == cursor.NAME:
        entities = project.location(line, col, indent).visible_entities()
        keywords = vocabulary.keywords()
    else:
        entities = {}
        for receiver in project.location(line, col, indent).evaluate(context.receiver):
            members = receiver.members()
            if receiver.kind == MODULE:
                members = dict(project.submodule_entities(receiver), **members)
            for name, entity in members.items():
                if receiver.kind == MODULE and name.startswith("_"):
                    continue
                entities.setdefault(name, entity)

    settings = config.active()
    case_sensitive = not settings.case_insensitive
    query = context.prefix
    results = []
    for name, entity in entities.items():
        if matching.matches(name, query, fuzzy, case_sensitive):
            kind, type_name = entity.presentation()
            results.append((name, False) + presentation.describe(name, kind, type_name))
    for word in keywords:
        if word not in entities and matching.matches(word, query, fuzzy, case_sensitive):
            results.append((word, True) + presentation.describe(word, presentation.KEYWORD))

    ordered = ranking.rank(results, name_of=lambda r: r[0], is_keyword=lambda r: r[1])
    bracket = "(" if settings.add_bracket else ""
    return [(name, matching.remaining_text(name, query)
             + (bracket if kind in ("function", "class") and not is_keyword else ""),
             kind, description)
            for name, is_keyword, kind, description in ordered]
