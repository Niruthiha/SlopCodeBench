"""The completion engine: ties context, parsing, scopes and inference together."""
import ast
import os
from dataclasses import asdict, dataclass

from . import context as cursor_context
from .builtin_scope import KEYWORDS
from .describe import describe_keyword, describe_module
from .inference import Inferrer
from .locate import find_scope
from .matching import make_matcher
from .members import is_public
from .modules import Importer, ModuleContext
from .parsing import parse_tolerant
from .ranking import sort_keywords, sort_names
from .source import load_document
from .values import MODULE


class ModuleEntry:
    """A module name offered inside an import statement."""

    def describe(self, name):
        return describe_module(name)


@dataclass
class Completion:
    name: str
    complete: str
    type: str
    description: str

    def to_dict(self):
        return asdict(self)


def complete_file(path, line, col, fuzzy=False, project=None):
    """Completions for the cursor at 1-based `line`, 0-based `col` of `path`."""
    document = load_document(path)
    document.check_position(line, col)
    return Completer(document, line, col, fuzzy, project).run()


class Completer:
    def __init__(self, document, line, col, fuzzy, project=None):
        self.document = document
        self.line = line
        self.col = col
        self.fuzzy = fuzzy
        self.project = project

    def run(self):
        text_before = self.document.text_before(self.line, self.col)
        import_request = cursor_context.analyze_import(text_before)
        request = import_request or cursor_context.analyze(text_before)
        if request.kind in (cursor_context.NONE, cursor_context.IMPORT_NOTHING):
            return []

        importer = Importer(os.path.abspath(self.project or self.document.directory))
        tree = parse_tolerant(self.document.text, cursor=(self.line, self.col))
        module = ModuleContext(self.document.path, "__main__", tree, self.document.text)
        importer.register(module)
        inferrer = Inferrer(importer)

        if import_request is not None:
            entries, keywords = self._import_entries(inferrer, module, import_request)
        elif request.kind == cursor_context.ATTRIBUTE:
            scope = find_scope(module, self.line, self.col, self.document.lines[self.line - 1])
            entries = self._attribute_entries(inferrer, scope, request.receiver)
            keywords = []
        else:
            scope = find_scope(module, self.line, self.col, self.document.lines[self.line - 1])
            entries = inferrer.visible_entries(scope, self.line)
            keywords = KEYWORDS
        return self._results(entries, keywords, request.prefix)

    def _results(self, entries, keywords, prefix):
        matches = make_matcher(prefix, self.fuzzy)
        cut = len(prefix)
        results = []
        for name in sort_names(n for n in entries if matches(n)):
            kind, description = entries[name].describe(name)
            results.append(Completion(name, name[cut:], kind, description))
        for name in sort_keywords(k for k in keywords if matches(k)):
            kind, description = describe_keyword(name)
            results.append(Completion(name, name[cut:], kind, description))
        return results

    def _import_entries(self, inferrer, context, request):
        """(entries, keywords) for a cursor inside an import statement."""
        importer = inferrer.importer
        if request.kind == cursor_context.IMPORT_KEYWORD:
            return {}, ["import"]
        if request.kind == cursor_context.IMPORT_MODULE:
            if request.level:
                package = importer.import_relative(context, request.module, request.level)
                names = importer.submodule_names(package)
            elif request.module:
                names = importer.submodule_names(importer.import_absolute(request.module))
            else:
                names = importer.top_level_names()
            return {name: ModuleEntry() for name in names}, []
        source = importer.import_module(context, request.module, request.level)
        if source is None or source.kind != MODULE:
            return {}, []
        return inferrer.members.exported(source, submodules=True), []

    def _attribute_entries(self, inferrer, scope, receiver):
        try:
            expression = ast.parse(receiver.strip(), mode="eval").body
        except (SyntaxError, ValueError):
            return {}
        line_text = self.document.lines[self.line - 1]
        position = (self.line, len(line_text[:self.col].encode("utf-8")))
        entries = {}
        for value in inferrer.infer_values(expression, scope, pos=position, strict=True):
            members = inferrer.members.all(value)
            if value.kind == MODULE:
                members = {name: entry for name, entry in members.items() if is_public(name)}
            for name, entry in members.items():
                entries.setdefault(name, entry)
        return entries
