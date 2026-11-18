"""The `inline` command: replace every use of a variable by its value."""
import ast

from .errors import SithError
from .references import PROJECT, search_references
from .refactoring import (Refactoring, Source, apply_edits, dump, replaced_tree, same_tree)
from .scopes import Binding
from .values import LocalModule


def inline(path, line, col, project=None):
    search = search_references(path, line, col, scope=PROJECT, project=project)
    occurrence = search.occurrence
    if occurrence.kind in ("constant", "text"):
        raise SithError(f"no name at line {line}, column {col}")
    name = occurrence.name
    binding = _definition(search)
    sources = {}

    def source_for(file_path):
        if file_path not in sources:
            sources[file_path] = Source(file_path)
        return sources[file_path]

    definition_source = source_for(binding.scope.module.path)
    statement = _strict_node(definition_source, binding.node)
    if statement is None:
        raise SithError(f"cannot find the definition of {name!r}")
    value = statement.value
    target = statement.target if isinstance(statement, ast.AnnAssign) else statement.targets[0]
    value_text = definition_source.segment(value)
    free_names = any(isinstance(node, ast.Name) for node in ast.walk(value))

    references = []  # (source, node to replace)
    imports = []  # (source, alias node) of `from ... import name` in other modules
    for match in search.matches:
        found = match.occurrence
        current = source_for(match.path)
        node = _strict_occurrence(current, match.line, found)
        if node is target:
            continue
        if node is None:
            raise SithError(f"cannot inline {name!r}: unsupported use at "
                            f"{match.module_path}:{match.line}:{found.start}")
        if isinstance(node, ast.alias):
            statement_node = current.parent(node)
            if node.asname or not isinstance(statement_node, ast.ImportFrom) \
                    or current is definition_source:
                raise SithError(f"cannot inline {name!r}: it is imported at "
                                f"{match.module_path}:{match.line}")
            imports.append((current, node))
            continue
        context = getattr(node, "ctx", None)
        if not isinstance(context, ast.Load):
            raise SithError(f"cannot inline {name!r}: it is assigned or deleted more than once "
                            f"({match.module_path}:{match.line})")
        if current is not definition_source and free_names:
            raise SithError(f"cannot inline {name!r} into another module: "
                            "its value depends on other names")
        references.append((current, node))
    if not references:
        raise SithError("name has no references to inline")

    edits = {}
    for current, node in references:
        start, end = current.start(node), current.end(node)
        edits.setdefault(current.path, []).append(
            (start, end, _replacement(current, node, value, value_text, start, end)))
    edits.setdefault(definition_source.path, []).append(
        _removal(definition_source, statement))
    for current, alias in imports:
        edits.setdefault(current.path, []).append(_import_removal(current, alias))
    refactoring = Refactoring(search.root)
    for file_path, file_edits in edits.items():
        current = sources[file_path]
        refactoring.change(file_path, current.text, apply_edits(current.text, file_edits))
    return refactoring


def _definition(search):
    """The single simple-assignment binding of the name at the cursor."""
    navigator = search.navigator
    name = search.occurrence.name
    try:
        sources = navigator.goto(search.occurrence)
    except Exception:
        sources = []
    definitions = []
    for source in sources:
        if isinstance(source, Binding) and source.kind in ("import", "importfrom"):
            followed = navigator._follow(source, set())
            if not followed:
                raise SithError(f"cannot inline {name!r}: it is imported from outside the project")
            definitions += followed
        else:
            definitions.append(source)
    if any(isinstance(d, LocalModule) for d in definitions):
        raise SithError("cannot inline a module")
    if not definitions or any(not isinstance(d, Binding) for d in definitions):
        raise SithError(f"cannot inline {name!r}: it is not defined in the project")
    unique = []
    for definition in definitions:
        if all(definition is not other for other in unique):
            unique.append(definition)
    if any(d.kind in ("def", "class") for d in unique):
        raise SithError("cannot inline a function/class definition")
    if len(unique) > 1:
        raise SithError(f"cannot inline {name!r}: it has more than one definition")
    binding = unique[0]
    if binding.kind == "param":
        raise SithError("cannot inline a parameter")
    node = binding.node
    simple = (
        binding.kind == "assign"
        and (isinstance(node, ast.Assign) and len(node.targets) == 1
             and isinstance(node.targets[0], ast.Name)
             or isinstance(node, ast.AnnAssign) and node.value is not None
             and isinstance(node.target, ast.Name))
    )
    if not simple or not binding.scope.module.path:
        raise SithError(f"cannot inline {name!r}: it is not defined by a simple assignment "
                        f"(`{name} = <expression>`)")
    return binding


def _strict_node(source, node):
    """The node of `source.tree` at the position of `node` (from another parse)."""
    for candidate in ast.walk(source.tree):
        if type(candidate) is type(node) and \
                (candidate.lineno, candidate.col_offset, candidate.end_lineno,
                 candidate.end_col_offset) == \
                (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset):
            return candidate
    return None


def _strict_occurrence(source, line, occurrence):
    """The Name, Attribute or alias node of `source.tree` that `occurrence` spells."""
    name = occurrence.name
    start = occurrence.start
    for node in ast.walk(source.tree):
        if isinstance(node, ast.Name):
            if node.id == name and node.lineno == line and \
                    source.char_col(line, node.col_offset) == start:
                return node
        elif isinstance(node, ast.Attribute):
            if node.attr == name and node.end_lineno == line and \
                    source.char_col(line, node.end_col_offset) == start + len(name):
                return node
        elif isinstance(node, ast.alias):
            if node.lineno == line and source.char_col(line, node.col_offset) == start and \
                    (node.asname or node.name) == name:
                return node
    return None


def _replacement(source, node, value, value_text, start, end):
    """`value_text`, parenthesized when the code around `node` would otherwise change meaning."""
    expected = dump(replaced_tree(source.tree, {id(node): value}))
    for candidate in (value_text, f"({value_text})"):
        if same_tree(source.text[:start] + candidate + source.text[end:], expected):
            return candidate
    return f"({value_text})"


def _removal(source, statement):
    """An edit deleting `statement` (replaced by `pass` when it is a block's only statement)."""
    start, end = source.start(statement), source.end(statement)
    text = source.text
    parent = source.parent(statement)
    siblings = None
    for field in ("body", "orelse", "finalbody", "handlers"):
        body = getattr(parent, field, None)
        if isinstance(body, list) and any(s is statement for s in body):
            siblings = body
    if siblings is not None and len(siblings) == 1 and not isinstance(parent, ast.Module):
        return start, end, "pass"
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    before = text[line_start:start]
    after = text[end:line_end]
    stripped_after = after.lstrip(" \t")
    if stripped_after.startswith(";"):
        following = end + (len(after) - len(stripped_after)) + 1
        while following < line_end and text[following] in " \t":
            following += 1
        if before.strip() or following < line_end and text[following] != "#":
            return start, following, ""
        stripped_after = text[following:line_end]
    if before.strip():
        semicolon = text.rfind(";", line_start, start)
        if semicolon >= 0 and not text[semicolon + 1:start].strip():
            return semicolon, end, ""
        return start, end, "pass"
    if stripped_after and not stripped_after.startswith("#"):
        return start, end, "pass"
    return line_start, min(line_end + 1, len(text)), ""


def _import_removal(source, alias):
    """An edit removing `alias` from its `from ... import` statement."""
    statement = source.parent(alias)
    remaining = [a for a in statement.names if a is not alias]
    if not remaining:
        return _removal(source, statement)
    names = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in remaining)
    module = "." * statement.level + (statement.module or "")
    return source.start(statement), source.end(statement), f"from {module} import {names}"
