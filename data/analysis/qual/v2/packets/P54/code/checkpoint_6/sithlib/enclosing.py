"""Enclosing scopes (``context``).

Secret: how the classes and functions surrounding a cursor are found (the
scope tree's notion of which scope a position belongs to) and how each is
described (name, kind and the position of the name in its header).
"""

from . import scopes
from .source import SourceFile


def context(path, line, col):
    """The class and function scopes around the cursor, outermost first: dicts
    with name, type, line and column."""
    source = SourceFile(path)
    source.check_position(line, col)
    tree = scopes.ScopeTree(source.text(), source.path)
    found = []
    scope = tree.scope_at(line, col)
    while scope is not None and scope.parent is not None:
        if scope.kind in (scopes.Scope.CLASS, scopes.Scope.FUNCTION) and scope.name:
            def_line, def_col = tree.definition_position(scope.node)
            found.append({"name": scope.name, "type": scope.kind,
                          "line": def_line, "column": def_col})
        scope = scope.parent
    return list(reversed(found))
