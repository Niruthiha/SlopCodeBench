"""Symbol listings (``references``, ``names``, ``search``).

Secret: which files a listing covers, which identifiers count as the same
symbol as the one under the cursor, which bindings each listing reports
(module level, every scope, or the searchable definitions), how a query
matches names, and how results are ordered.
"""

import os
import re

from . import navigation, scopes
from .inference import Project
from .modules import project_files
from .source import SourceFile

FILE = "file"
PROJECT = "project"


def references(path, line, col, scope=FILE, root=None):
    """Occurrences of the symbol at the cursor: dicts of module_path, line,
    column and is_definition."""
    source = SourceFile(path)
    source.check_position(line, col)
    project = Project(source.path, source.text(), root)
    found = navigation.find(project.main, line, col)
    if found is None:
        raise navigation.NotOnName("no name at %d:%d" % (line, col))
    describer = navigation.describer(project)
    results = {}
    for file_path, number, column, _, definition in occurrences_of(project, found, scope):
        key = (describer.relative(file_path), number, column)
        results[key] = results.get(key, False) or definition
    return [{"module_path": module_path, "line": number, "column": column,
             "is_definition": definition}
            for (module_path, number, column), definition in sorted(results.items())]


def occurrences_of(project, found, scope=FILE):
    """Occurrences of the symbol ``found`` (as returned by ``navigation.find`` on
    ``project.main``): ``(path, line, column, occurrence or None, is_definition)``,
    possibly repeated."""
    name, _, _, occurrence = found
    main_path = project.main.path
    wanted = navigation.identity(project, occurrence)
    paths = [main_path]
    if scope == PROJECT:
        paths += [p for p in project_files(project.root) if os.path.abspath(p) != main_path]
    pattern = re.compile(r"(?<!\w)%s(?!\w)" % re.escape(name))
    for file_path in paths:
        if file_path != main_path and not _mentions(file_path, pattern):
            continue
        analysis = project.analysis(file_path)
        for number, column, candidate in navigation.occurrences(analysis, name):
            keys = navigation.identity(project, candidate)
            if keys & wanted or (not wanted and not keys and file_path == main_path):
                yield file_path, number, column, candidate, candidate.is_definition()
    covered = {os.path.abspath(p) for p in paths}
    for site_path, number, column in navigation.definition_sites(occurrence, project):
        if site_path and os.path.abspath(site_path) in covered:
            yield site_path, number, column, None, True


def names(path, all_scopes=False, root=None):
    """Definition records (plus ``is_definition``) of the names bound in a file."""
    source = SourceFile(path)
    project = Project(source.path, source.text(), root)
    tree = project.main.tree
    if all_scopes:
        bindings = list(_all_bindings(tree.module))
    else:
        bindings = [b for b in tree.module.events if b.home is tree.module]
    describer = navigation.describer(project)
    records = {}
    for binding in bindings:
        if binding.form == scopes.STAR or not binding.name:
            continue
        record = describer.binding(binding)
        if record is not None:
            record["is_definition"] = True
            records.setdefault((record["line"], record["column"], record["name"]), record)
    return [records[key] for key in sorted(records)]


def search(query, root=None):
    """Definition records (without docstrings) of the project's searchable names
    containing ``query``, best matches first."""
    root = os.path.abspath(root or os.getcwd())
    project = Project(None, None, root)
    describer = navigation.describer(project)
    wanted = query.lower()
    found = {}
    for file_path in project_files(root):
        tree = project.analysis(file_path).tree
        for binding in _searchable(tree.module):
            lowered = binding.name.lower()
            if wanted not in lowered:
                continue
            record = describer.binding(binding)
            if record is None:
                continue
            record.pop("docstring", None)
            rank = 0 if lowered == wanted else 1 if lowered.startswith(wanted) else 2
            key = (rank, record["module_path"], record["line"], record["column"], record["name"])
            found.setdefault(key, record)
    return [found[key] for key in sorted(found)]


def _mentions(path, pattern):
    try:
        with open(path, "rb") as handle:
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    return pattern.search(text) is not None


def _all_bindings(scope):
    yield from scope.events
    yield from scope.instance_events
    for child in scope.children:
        yield from _all_bindings(child)


def _searchable(scope):
    """Functions and classes outside function bodies, and module-level assignments."""
    for binding in scope.events:
        if binding.home is not scope or not binding.name:
            continue
        if binding.form in (scopes.DEF, scopes.CLASS) or \
                (binding.form == scopes.ASSIGN and scope.kind == scopes.Scope.MODULE):
            yield binding
    for child in scope.children:
        if child.kind == scopes.Scope.CLASS:
            yield from _searchable(child)
