"""The `rename` command: rename a symbol (or a module) and every reference to it."""
import os

from .errors import SithError
from .references import PROJECT, search_references
from .refactoring import Refactoring, apply_edits, check_identifier
from .scopes import CLASS, Binding
from .values import LocalClass

# Occurrence kinds that bind the name they spell.
_BINDING_KINDS = ("def", "param", "bound")


def rename(path, line, col, new_name, project=None):
    check_identifier(new_name)
    search = search_references(path, line, col, scope=PROJECT, project=project)
    occurrence = search.occurrence
    if occurrence.kind == "constant":
        raise SithError(f"no name at line {line}, column {col}")
    old_name = occurrence.name
    refactoring = Refactoring(search.root)
    kinds = {symbol[0] for symbol in search.target}
    if kinds & {"builtin", "runtime"}:
        raise SithError(f"cannot rename {old_name!r}: it is defined outside the project")
    modules = [symbol[1] for symbol in search.target if symbol[0] == "module"]
    if modules:
        _rename_module(search, modules[0], old_name, new_name, refactoring)
    elif new_name != old_name:
        _check_collisions(search, new_name)
    if new_name == old_name:
        return refactoring
    edits = {}
    for match in search.matches:
        context = match.navigator.context
        start = match.occurrence.start
        if context.lines[match.line - 1][start:start + len(old_name)] != old_name:
            continue
        files = edits.setdefault(match.path, (context.text, set()))
        files[1].add(_offset(context.lines, match.line, start))
    for file_path, (old_text, starts) in edits.items():
        new_text = apply_edits(old_text, [(s, s + len(old_name), new_name) for s in starts])
        refactoring.change(file_path, old_text, new_text)
    return refactoring


def _offset(lines, line, col):
    return sum(len(text) + 1 for text in lines[:line - 1]) + col


def _rename_module(search, location, old_name, new_name, refactoring):
    """Rename the file or directory of a project module."""
    importer = search.importer
    location = os.path.abspath(location)
    if not importer.within_project(os.path.dirname(location)) or \
            importer.within_project(location) and location.startswith(importer.stub_dir + os.sep):
        raise SithError(f"cannot rename module {old_name!r}: it is outside the project")
    if os.path.isdir(location):
        old_path = location
    elif os.path.basename(location) in ("__init__.py", "__init__.pyi"):
        old_path = os.path.dirname(location)
    else:
        old_path = location
    base = os.path.basename(old_path)
    stem, extension = (base, "") if os.path.isdir(old_path) else os.path.splitext(base)
    if stem != old_name:
        raise SithError(f"cannot rename module {stem!r} through the name {old_name!r}")
    if new_name == old_name:
        return
    directory = os.path.dirname(old_path)
    new_path = os.path.join(directory, new_name + extension)
    for candidate in (os.path.join(directory, new_name), os.path.join(directory, new_name + ".py"),
                      os.path.join(directory, new_name + ".pyi")):
        if os.path.exists(candidate):
            raise SithError(f"cannot rename module {old_name!r} to {new_name!r}: "
                            f"{os.path.relpath(candidate, search.root)} already exists")
    refactoring.rename(old_path, new_path)


def _check_collisions(search, new_name):
    """Refuse renames that would clash with a name already bound where the symbol is used."""
    navigator = search.navigator
    try:
        sources = navigator.goto(search.occurrence)
    except Exception:
        sources = []
    for source in sources:
        owner = source.extra.get("owner") if isinstance(source, Binding) else None
        if owner is not None and _class_binds(search, owner, new_name):
            _collision(search, new_name, owner)
    for match in search.matches:
        current = match.navigator
        occurrence = match.occurrence
        if occurrence.kind in ("attr", "kwarg", "module", "imported"):
            continue
        current.at(match.line, occurrence.start)
        binding = current.context.binding_of(occurrence.node) \
            if occurrence.kind in _BINDING_KINDS and occurrence.node is not None else None
        if binding is not None:
            if new_name in binding.scope.bindings or \
                    binding.scope.kind == CLASS and _class_binds(search, binding.scope, new_name):
                _collision(search, new_name, binding.scope)
            continue
        scope = current.scope()
        for candidate in scope.chain():
            if candidate.kind == CLASS and candidate is not scope:
                continue
            if new_name in candidate.bindings:
                _collision(search, new_name, candidate)


def _class_binds(search, scope, name):
    if name in scope.bindings:
        return True
    members = search.inferrer.members
    try:
        return name in members.instance_attribute_bindings(LocalClass(scope))
    except Exception:
        return False


def _collision(search, new_name, scope):
    node = scope.node
    where = f"{node.name!r}" if hasattr(node, "name") else "the module"
    if scope.kind == "module":
        where = search.factory.relative_path(scope.module.path) or "the module"
    raise SithError(f"cannot rename to {new_name!r}: the name {new_name!r} already exists "
                    f"in the scope of {where}")
