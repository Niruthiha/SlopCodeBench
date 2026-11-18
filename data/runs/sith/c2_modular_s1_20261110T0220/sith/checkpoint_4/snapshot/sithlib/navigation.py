"""The `infer` and `goto` commands: what a name evaluates to, and where it is defined."""
import ast
import keyword
import os
import re
from dataclasses import dataclass, field

from . import context as cursor_context
from .definitions import DefinitionFactory, char_column, find_word, sorted_unique
from .errors import SithError
from .inference import Inferrer, RuntimeInstance
from .locate import find_scope
from .modules import Importer, ModuleContext
from .parsing import parse_tolerant, strip_comment
from .source import load_document
from .scopes import Binding
from .values import LocalClass, LocalFunction, LocalInstance, LocalModule, unique

INFER = "infer"
GOTO = "goto"


@dataclass
class Occurrence:
    """An identifier in the source and the role it plays there."""

    kind: str
    name: str
    start: int
    end: int
    node: ast.AST = None
    extra: dict = field(default_factory=dict)


def navigate(command, path, line, col, project=None, follow_imports=False):
    """Definitions for `command` ("infer" or "goto") at the cursor in `path`.

    With `follow_imports`, `goto` follows import statements to the
    definitions they import.
    """
    document = load_document(path)
    document.check_position(line, col)
    root = os.path.abspath(project or document.directory)
    importer = Importer(root)
    tree = parse_tolerant(document.text)
    context = ModuleContext(document.path, "__main__", tree, document.text)
    importer.register(context)
    inferrer = Inferrer(importer)
    navigator = Navigator(context, inferrer, DefinitionFactory(inferrer, root), line, col)
    occurrence = navigator.occurrence()
    if occurrence is None:
        raise SithError(f"no name at line {line}, column {col}")
    if command == GOTO:
        sources = navigator.goto(occurrence)
        if follow_imports:
            sources = navigator.follow_imports(sources)
    else:
        sources = navigator.infer(occurrence)
    factory = navigator.factory
    return sorted_unique(factory.from_source(source) for source in sources)


class Navigator:
    def __init__(self, context, inferrer, factory, line=1, col=0):
        self.context = context
        self.inferrer = inferrer
        self.factory = factory
        self.parents = {}
        # Nodes starting or ending on each line, in `ast.walk` order.
        self.nodes_by_line = {}
        for parent in ast.walk(context.tree):
            for number in {getattr(parent, "lineno", None), getattr(parent, "end_lineno", None)}:
                if number is not None:
                    self.nodes_by_line.setdefault(number, []).append(parent)
            for child in ast.iter_child_nodes(parent):
                self.parents[id(child)] = parent
        self.at(line, col)

    def at(self, line, col):
        """Move the cursor to 1-based `line`, 0-based character `col`."""
        self.line = line
        self.col = col
        self.text = self.context.lines[line - 1] if 0 < line <= len(self.context.lines) else ""
        return self

    # -- locating the identifier under the cursor ---------------------------------

    def occurrence(self):
        candidates = list(self._occurrences())
        inside = [o for o in candidates if o.start <= self.col < o.end]
        touching = [o for o in candidates if o.start <= self.col <= o.end]
        for group in (inside, touching):
            if group:
                return min(group, key=lambda o: o.end - o.start)
        return self._textual_occurrence()

    def _char(self, byte_col):
        return char_column(self.context, self.line, byte_col)

    def occurrences(self):
        """Every identifier occurrence on the cursor line."""
        return list(self._occurrences())

    def _occurrences(self):
        line = self.line
        for node in self.nodes_by_line.get(line, []):
            if isinstance(node, ast.Name):
                if node.lineno == line == node.end_lineno:
                    yield Occurrence("name", node.id, self._char(node.col_offset),
                                     self._char(node.end_col_offset), node)
            elif isinstance(node, ast.Attribute):
                if node.end_lineno == line:
                    end = self._char(node.end_col_offset)
                    start = end - len(node.attr)
                    if self.text[start:end] == node.attr:
                        yield Occurrence("attr", node.attr, start, end, node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.lineno == line:
                    match = re.compile(r"(?:async\s+)?(?:def|class)\s+").match(
                        self.text, self._char(node.col_offset))
                    if match and self.text.startswith(node.name, match.end()):
                        yield Occurrence("def", node.name, match.end(),
                                         match.end() + len(node.name), node)
            elif isinstance(node, ast.arg):
                if node.lineno == line:
                    start = self._char(node.col_offset)
                    yield Occurrence("param", node.arg, start, start + len(node.arg), node)
            elif isinstance(node, ast.alias):
                yield from self._alias_occurrences(node)
            elif isinstance(node, ast.ImportFrom):
                yield from self._import_from_module(node)
            elif isinstance(node, ast.keyword):
                if node.arg is not None and node.lineno == line:
                    start = self._char(node.col_offset)
                    yield Occurrence("kwarg", node.arg, start, start + len(node.arg), node,
                                     {"call": self.parents.get(id(node))})
            elif isinstance(node, ast.ExceptHandler):
                if node.name and node.lineno == line:
                    match = re.search(r"\bas\s+(" + re.escape(node.name) + r")\b", self.text)
                    if match:
                        yield Occurrence("bound", node.name, match.start(1), match.end(1), node)
            elif isinstance(node, (ast.MatchAs, ast.MatchStar, ast.MatchMapping)):
                name = getattr(node, "name", None) or getattr(node, "rest", None)
                if name and node.end_lineno == line:
                    end = self._char(node.end_col_offset)
                    start = self.text.rfind(name, 0, end)
                    if start >= 0:
                        yield Occurrence("bound", name, start, start + len(name), node)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                if node.lineno == line:
                    position = self._char(node.col_offset)
                    for name in node.names:
                        found = find_word(self.text, name, position + 1)
                        if found is not None:
                            position = found
                            yield Occurrence("name", name, found, found + len(name), node)
            elif isinstance(node, ast.Constant):
                if node.value is None or isinstance(node.value, bool):
                    if node.lineno == line == node.end_lineno:
                        yield Occurrence("constant", repr(node.value), self._char(node.col_offset),
                                         self._char(node.end_col_offset), node)

    def _alias_occurrences(self, alias):
        if alias.lineno != self.line or alias.name == "*":
            return
        statement = self.parents.get(id(alias))
        start = self._char(alias.col_offset)
        if isinstance(statement, ast.Import):
            position = start
            parts = alias.name.split(".")
            for index, part in enumerate(parts):
                found = self.text.find(part, position)
                if found < 0:
                    break
                if index == 0 and not alias.asname:
                    yield Occurrence("bound", part, found, found + len(part), alias)
                else:
                    yield Occurrence("module", part, found, found + len(part), alias,
                                     {"module": ".".join(parts[:index + 1]), "level": 0})
                position = found + len(part)
        elif isinstance(statement, ast.ImportFrom):
            if alias.asname:
                yield Occurrence("imported", alias.name, start, start + len(alias.name), alias,
                                 {"statement": statement})
        else:
            return
        if isinstance(statement, ast.ImportFrom) and not alias.asname:
            yield Occurrence("bound", alias.name, start, start + len(alias.name), alias)
        if alias.asname:
            found = find_word(self.text, alias.asname, start + len(alias.name))
            if found is not None:
                yield Occurrence("bound", alias.asname, found, found + len(alias.asname), alias)

    def _import_from_module(self, node):
        if node.lineno != self.line:
            return
        match = re.compile(r"from\s+(\.*)\s*([\w.]*)").match(self.text, self._char(node.col_offset))
        if not match or not match.group(2):
            return
        position = match.start(2)
        parts = match.group(2).split(".")
        for index, part in enumerate(parts):
            yield Occurrence("module", part, position, position + len(part), node,
                             {"module": ".".join(parts[:index + 1]), "level": node.level})
            position += len(part) + 1

    def _textual_occurrence(self):
        """An identifier the parser lost (e.g. on a repaired line), if any."""
        text = self.text
        if self.col > len(strip_comment(text)) or self._in_string():
            return None
        start = end = self.col
        while start > 0 and cursor_context.is_identifier_char(text[start - 1]):
            start -= 1
        while end < len(text) and cursor_context.is_identifier_char(text[end]):
            end += 1
        word = text[start:end]
        if not word or word[0].isdigit() or keyword.iskeyword(word) or not word.isidentifier():
            return None
        receiver = None
        if text[:start].rstrip().endswith("."):
            before = "\n".join(self.context.lines[:self.line - 1] + [text[:start].rstrip()[:-1]])
            receiver = cursor_context.extract_receiver(before)
            if not receiver:
                return None
        return Occurrence("text", word, start, end, None, {"receiver": receiver})

    def _in_string(self):
        for node in ast.walk(self.context.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
                start = (node.lineno, self._char(node.col_offset) if node.lineno == self.line else -1)
                end = (node.end_lineno, self._char(node.end_col_offset)
                       if node.end_lineno == self.line else 1 << 30)
                if start <= (self.line, self.col) < end:
                    return True
        return False

    # -- resolution ----------------------------------------------------------------

    def scope(self):
        return find_scope(self.context, self.line, self.col, self.text)

    def _byte_position(self, col):
        return (self.line, len(self.text[:col].encode("utf-8")))

    def goto(self, occurrence):
        """Bindings (or values, for runtime objects) defining the name at the cursor."""
        handler = getattr(self, "_goto_" + occurrence.kind)
        return handler(occurrence)

    def follow_imports(self, sources):
        """Replace import bindings among `sources` by the definitions they import.

        An import whose chain ends outside the project (stdlib, third-party or
        missing modules) is kept as it is: the import site is the fallback.
        """
        result = []
        for source in sources:
            followed = self._follow(source, set()) if _is_import(source) else None
            result += followed or [source]
        return result

    def _follow(self, binding, seen):
        """Definitions at the end of the import chain starting at `binding` ([] if unresolvable)."""
        if id(binding) in seen:
            return []
        seen.add(id(binding))
        importer = self.inferrer.importer
        if binding.kind == "import":
            module = importer.import_absolute(binding.extra.get("module", ""))
            return [module] if isinstance(module, LocalModule) else []
        context = binding.scope.module
        base = importer.import_module(context, binding.extra.get("module", ""),
                                      binding.extra.get("level", 0))
        if not isinstance(base, LocalModule):
            return []
        name = binding.extra.get("attribute", binding.name)
        root = base.context.root
        if not self.inferrer.binds(root, name):
            stub = self.inferrer.stubs.stub_scope(root)
            if stub is not None and self.inferrer.binds(stub, name):
                root = stub
            else:
                submodule = importer.local_submodule(base, name)
                return [submodule] if submodule is not None else []
        result = []
        for fact in self.inferrer.scope_facts(root, name):
            target = fact.binding
            if _is_import(target):
                result += self._follow(target, seen)
            else:
                result.append(target)
        return result

    def infer(self, occurrence):
        """Values the name at the cursor evaluates to."""
        handler = getattr(self, "_infer_" + occurrence.kind)
        return unique(handler(occurrence))

    # names

    def _name_facts(self, occurrence):
        node = occurrence.node
        position = (node.lineno, node.col_offset) if isinstance(node, ast.Name) else \
            self._byte_position(occurrence.start)
        return self.inferrer.name_facts(occurrence.name, self.scope(), position)

    def _store_binding(self, occurrence):
        node = occurrence.node
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            binding = self.context.binding_of(node)
            if binding is not None:
                return binding
            parent = self.parents.get(id(node))
            if isinstance(parent, ast.AugAssign):
                scope = self.scope()
                return self.inferrer.synthetic_binding(scope)("aug", parent, node.id)
        return None

    def _goto_name(self, occurrence):
        binding = self._store_binding(occurrence)
        if binding is not None:
            return [binding]
        return [fact.binding for fact in self._name_facts(occurrence)]

    def _infer_name(self, occurrence):
        binding = self._store_binding(occurrence)
        if binding is not None and binding.kind != "augassign":
            return self.inferrer.binding_values(binding)
        values = []
        for fact in self._name_facts(occurrence):
            values += self.inferrer.fact_values(fact)
        return values

    # attributes

    def _instance_attribute(self, occurrence, bases):
        """The `self.attr = ...` binding at the cursor, with the instance it belongs to."""
        node = occurrence.node
        for base in bases:
            if isinstance(base, LocalInstance):
                for cls in self.inferrer.members.mro(base.cls):
                    for binding in self.inferrer.members.instance_attribute_bindings(cls).get(
                            occurrence.name, []):
                        if binding.target is node:
                            return binding, base
        return None, None

    def _goto_attr(self, occurrence):
        node = occurrence.node
        bases = self.inferrer.infer_values(node.value, self.scope())
        if isinstance(node.ctx, ast.Store):
            binding, _ = self._instance_attribute(occurrence, bases)
            if binding is not None:
                return [binding]
        sources = []
        for base in bases:
            sources += self.inferrer.members.member_definitions(base, occurrence.name)
        return sources

    def _infer_attr(self, occurrence):
        node = occurrence.node
        bases = self.inferrer.infer_values(node.value, self.scope())
        if isinstance(node.ctx, ast.Store):
            binding, instance = self._instance_attribute(occurrence, bases)
            if binding is not None:
                return self.inferrer.members.instance_attribute_values(binding, instance)
        values = []
        for base in bases:
            values += self.inferrer.members.member_values(base, occurrence.name)
        return values

    # definitions and other bound names

    def _bound_binding(self, occurrence):
        return self.context.binding_of(occurrence.node)

    def _goto_bound(self, occurrence):
        binding = self._bound_binding(occurrence)
        return [binding] if binding is not None else []

    def _infer_bound(self, occurrence):
        binding = self._bound_binding(occurrence)
        return self.inferrer.binding_values(binding) if binding is not None else []

    _goto_def = _goto_param = _goto_bound
    _infer_def = _infer_param = _infer_bound

    # modules named in import statements

    def _module_value(self, occurrence):
        module = self.inferrer.importer.import_module(
            self.context, occurrence.extra["module"], occurrence.extra["level"])
        return [module] if module is not None else []

    _goto_module = _infer_module = _module_value

    def _goto_imported(self, occurrence):
        statement = occurrence.extra["statement"]
        base = self.inferrer.importer.import_module(self.context, statement.module or "",
                                                    statement.level)
        if base is not None:
            found = self.inferrer.members.member_definitions(base, occurrence.name)
            if found:
                return found
        return self._infer_imported(occurrence)

    def _infer_imported(self, occurrence):
        statement = occurrence.extra["statement"]
        return self.inferrer.resolve_from_values(self.context, statement.module or "",
                                                 statement.level, occurrence.name)

    # keyword arguments

    def _keyword_parameters(self, occurrence):
        call = occurrence.extra.get("call")
        if not isinstance(call, ast.Call):
            return []
        bindings = []
        for function in self.inferrer.infer_values(call.func, self.scope()):
            if isinstance(function, LocalClass):
                init = self.inferrer.members.find_method(function, "__init__")
                if init is None:
                    # Generated `__init__` (dataclasses and the like): parameters are the fields.
                    for cls in self.inferrer.members.mro(function):
                        bindings += [b for b in cls.scope.bindings.get(occurrence.name, [])
                                     if b.extra.get("annotation") is not None]
                    continue
                function = init
            elif isinstance(function, LocalInstance):
                function = self.inferrer.members.find_method(function.cls, "__call__")
            if isinstance(function, LocalFunction):
                bindings += [b for b in function.scope.bindings.get(occurrence.name, [])
                             if b.kind == "param"]
        return bindings

    def _goto_kwarg(self, occurrence):
        return self._keyword_parameters(occurrence)

    def _infer_kwarg(self, occurrence):
        values = []
        for binding in self._keyword_parameters(occurrence):
            values += self.inferrer.binding_values(binding)
        return values

    # literals

    def _goto_constant(self, occurrence):
        return []

    def _infer_constant(self, occurrence):
        return [RuntimeInstance(type(occurrence.node.value))]

    # identifiers missing from the (repaired) syntax tree

    def _text_receiver_values(self, occurrence):
        try:
            expression = ast.parse(occurrence.extra["receiver"].strip(), mode="eval").body
        except (SyntaxError, ValueError):
            return []
        return self.inferrer.infer_values(expression, self.scope(),
                                          pos=self._byte_position(occurrence.start))

    def _goto_text(self, occurrence):
        if occurrence.extra.get("receiver"):
            sources = []
            for base in self._text_receiver_values(occurrence):
                sources += self.inferrer.members.member_definitions(base, occurrence.name)
            return sources
        return [fact.binding for fact in self._name_facts(occurrence)]

    def _infer_text(self, occurrence):
        if occurrence.extra.get("receiver"):
            values = []
            for base in self._text_receiver_values(occurrence):
                values += self.inferrer.members.member_values(base, occurrence.name)
            return values
        values = []
        for fact in self._name_facts(occurrence):
            values += self.inferrer.fact_values(fact)
        return values


def _is_import(source):
    return isinstance(source, Binding) and source.kind in ("import", "importfrom")
