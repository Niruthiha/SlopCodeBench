"""The `references` command: every occurrence of the symbol under the cursor.

Occurrences are matched by symbol identity, not spelling: a symbol is the
scope a name is bound in plus the name (the owning class for attributes), with
imports followed to what they import, a module, or a runtime object.
"""
import ast
import os
import re
from dataclasses import asdict, dataclass

from .definitions import DefinitionFactory
from .errors import SithError
from .inference import BuiltinBinding, Inferrer
from .modules import Importer
from .navigation import Navigator
from .project import project_files
from .scopes import Binding
from .source import load_document, read_text
from .values import LocalClass, LocalFunction, LocalInstance, LocalModule

FILE = "file"
PROJECT = "project"
_DEFINING_KINDS = ("def", "param", "bound")


@dataclass
class Reference:
    module_path: str
    line: int
    column: int
    is_definition: bool

    def to_dict(self):
        return asdict(self)


def find_references(path, line, col, scope=FILE, project=None):
    """References to the name at the cursor, in `path` or (`scope` "project") the whole project."""
    document = load_document(path)
    document.check_position(line, col)
    root = os.path.abspath(project or document.directory)
    importer = Importer(root)
    context = importer.context_for_file(document.path)
    if context is None:
        raise SithError(f"cannot analyze {path}")
    inferrer = Inferrer(importer)
    factory = DefinitionFactory(inferrer, root)
    navigator = Navigator(context, inferrer, factory, line, col)
    occurrence = navigator.occurrence()
    if occurrence is None:
        raise SithError(f"no name at line {line}, column {col}")
    finder = _Finder(inferrer)
    target = finder.symbols(navigator, line, occurrence)
    name = occurrence.name
    navigators = [navigator]
    if scope == PROJECT:
        word = _word(name)
        for file_path in project_files(root):
            if os.path.abspath(file_path) == context.path:
                continue
            try:
                if not word.search(read_text(file_path)):
                    continue
            except SithError:
                continue
            other = importer.context_for_file(file_path)
            if other is not None:
                navigators.append(Navigator(other, inferrer, factory))
    found = {}
    for current in navigators:
        module_path = factory.relative_path(current.context.path)
        for number, occurrence_found in _named_occurrences(current, name):
            if target:
                matches = bool(finder.symbols(current, number, occurrence_found) & target)
            else:
                # Unresolved name: match the other unresolved uses in the same file.
                matches = current is navigator and not finder.symbols(current, number,
                                                                       occurrence_found)
            if matches:
                key = (module_path, number, occurrence_found.start)
                defining = _is_definition(occurrence_found)
                found[key] = found.get(key, False) or defining
    if occurrence.kind == "text":  # an identifier missing from the (repaired) syntax tree
        found.setdefault((factory.relative_path(context.path), line, occurrence.start), False)
    return [Reference(path_, number, column, defining)
            for (path_, number, column), defining in sorted(found.items())]


def _word(name):
    return re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)")


def _named_occurrences(navigator, name):
    """(line, occurrence) for every occurrence of `name` in the navigator's module."""
    word = _word(name)
    for number, text in enumerate(navigator.context.lines, start=1):
        if not word.search(text):
            continue
        navigator.at(number, 0)
        starts = set()
        for occurrence in navigator.occurrences():
            if occurrence.name == name and occurrence.start not in starts:
                starts.add(occurrence.start)
                yield number, occurrence


def _is_definition(occurrence):
    if occurrence.kind in _DEFINING_KINDS:
        return True
    if occurrence.kind in ("name", "attr"):
        return isinstance(getattr(occurrence.node, "ctx", None), ast.Store)
    return False


class _Finder:
    def __init__(self, inferrer):
        self.inferrer = inferrer

    def symbols(self, navigator, line, occurrence):
        """The set of symbols the occurrence at `line` refers to."""
        navigator.at(line, occurrence.start)
        try:
            sources = navigator.goto(occurrence)
        except Exception:
            return set()
        return self._symbols(navigator, sources)

    def _symbols(self, navigator, sources):
        result = set()
        for source in sources:
            if source is None:
                continue
            if isinstance(source, BuiltinBinding):
                result.add(("builtin", source.name))
            elif isinstance(source, Binding):
                if source.kind in ("import", "importfrom"):
                    result |= self._import_symbols(navigator, source)
                else:
                    owner = source.extra.get("owner")
                    result.add(("scope", id(owner or source.scope), source.name))
            else:
                result.add(_value_symbol(source))
        return result

    def _import_symbols(self, navigator, binding):
        followed = navigator._follow(binding, set())
        if followed:
            return self._symbols(navigator, followed)
        values = [v for v in self.inferrer.binding_values(binding) if v is not None]
        if values:
            return {_value_symbol(v) for v in values}
        return {("scope", id(binding.scope), binding.name)}


def _value_symbol(value):
    if isinstance(value, LocalModule):
        return ("module", value.context.location)
    if isinstance(value, (LocalClass, LocalFunction)):
        node = value.scope.node
        if isinstance(node, ast.Lambda):
            return ("node", id(node))
        return ("scope", id(value.scope.parent), node.name)
    if isinstance(value, LocalInstance):
        return ("instance", id(value.cls.scope))
    return ("runtime",) + value.key
