"""The completion engine: ties context, parsing, scopes and inference together."""
import ast
from dataclasses import asdict, dataclass

from . import context as cursor_context
from .builtin_scope import KEYWORDS
from .describe import describe_keyword
from .inference import Inferrer
from .locate import find_scope
from .matching import make_matcher
from .members import is_public
from .modules import Importer, ModuleContext
from .parsing import parse_tolerant
from .ranking import sort_keywords, sort_names
from .source import load_document
from .values import MODULE


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
        request = cursor_context.analyze(self.document.text_before(self.line, self.col))
        if request.kind == cursor_context.NONE:
            return []

        importer = Importer(self.project or self.document.directory, self.document.directory)
        tree = parse_tolerant(self.document.text, cursor=(self.line, self.col))
        module = ModuleContext(self.document.path, "__main__", tree, self.document.text)
        importer.register(module)
        inferrer = Inferrer(importer)
        scope = find_scope(module, self.line, self.col, self.document.lines[self.line - 1])

        if request.kind == cursor_context.ATTRIBUTE:
            entries = self._attribute_entries(inferrer, scope, request.receiver)
            keywords = []
        else:
            entries = inferrer.visible_entries(scope, self.line)
            keywords = KEYWORDS

        matches = make_matcher(request.prefix, self.fuzzy)
        cut = len(request.prefix)
        results = []
        for name in sort_names(n for n in entries if matches(n)):
            kind, description = entries[name].describe(name)
            results.append(Completion(name, name[cut:], kind, description))
        for name in sort_keywords(k for k in keywords if matches(k)):
            kind, description = describe_keyword(name)
            results.append(Completion(name, name[cut:], kind, description))
        return results

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
