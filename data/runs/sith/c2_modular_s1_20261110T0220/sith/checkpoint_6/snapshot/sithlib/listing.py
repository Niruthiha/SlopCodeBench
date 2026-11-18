"""The `search` and `names` commands: definitions across a project or within a file."""
import os

from .definitions import DefinitionFactory
from .errors import SithError
from .inference import Inferrer
from .modules import Importer
from .project import project_files
from .scopes import CLASS
from .source import load_document
from .values import LocalClass

_SEARCHED_KINDS = ("def", "class")


def search_project(query, project=None):
    """Definitions in the project whose names contain `query` (case-insensitive).

    Exact matches come first, then prefix matches, then other substring matches.
    """
    root = os.path.abspath(project or os.getcwd())
    if not os.path.isdir(root):
        raise SithError(f"not a directory: {root}")
    importer = Importer(root)
    inferrer = Inferrer(importer)
    factory = DefinitionFactory(inferrer, root)
    needle = query.lower()
    ranked = []
    for path in project_files(root):
        context = importer.context_for_file(path)
        if context is None:
            continue
        for binding in _searchable_bindings(context.root):
            name = binding.name.lower()
            if needle not in name:
                continue
            rank = 0 if name == needle else 1 if name.startswith(needle) else 2
            definition = factory.from_binding(binding)
            ranked.append(((rank,) + definition.sort_key, definition))
    results = []
    seen = set()
    for _, definition in sorted(ranked, key=lambda pair: pair[0]):
        entry = definition.to_dict()
        del entry["docstring"]
        identity = tuple(entry.items())
        if identity not in seen:
            seen.add(identity)
            results.append(entry)
    return results


def _searchable_bindings(root):
    """Module-level defs, classes and assignments, plus defs and classes nested in classes."""
    result = []
    for bindings in root.bindings.values():
        result += [b for b in bindings if b.kind in _SEARCHED_KINDS + ("assign",)]
    classes = [root.module.scope_of(b.node) for b in result if b.kind == "class"]
    while classes:
        scope = classes.pop()
        if scope is None or scope.kind != CLASS:
            continue
        for bindings in scope.bindings.values():
            for binding in bindings:
                if binding.kind in _SEARCHED_KINDS:
                    result.append(binding)
                    if binding.kind == "class":
                        classes.append(scope.module.scope_of(binding.node))
    return result


def list_names(path, all_scopes=False, project=None):
    """Definitions made in the file at `path`, module-level only unless `all_scopes`."""
    document = load_document(path)
    root = os.path.abspath(project or document.directory)
    importer = Importer(root)
    context = importer.context_for_file(document.path)
    if context is None:
        raise SithError(f"cannot analyze {path}")
    inferrer = Inferrer(importer)
    factory = DefinitionFactory(inferrer, root)
    scopes = [context.root]
    if all_scopes:
        index = 0
        while index < len(scopes):
            scopes += scopes[index].children
            index += 1
    bindings = []
    for scope in scopes:
        for found in scope.bindings.values():
            bindings += found
        if all_scopes and scope.kind == CLASS:
            for found in inferrer.members.instance_attribute_bindings(LocalClass(scope)).values():
                bindings += found
    entries = {}
    for binding in bindings:
        definition = factory.from_binding(binding)
        key = (definition.line, definition.column)
        if key not in entries:
            entry = definition.to_dict()
            entry["is_definition"] = True
            entries[key] = entry
    return [entries[key] for key in sorted(entries)]
