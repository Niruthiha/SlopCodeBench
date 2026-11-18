"""The `context` command: the classes and functions enclosing a cursor position."""
import ast
import re
from dataclasses import asdict, dataclass

from .definitions import char_column
from .locate import find_scope
from .modules import ModuleContext
from .parsing import parse_tolerant
from .scopes import CLASS, FUNCTION
from .source import load_document

_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_DEFINITION_HEADER = re.compile(r"(?:async\s+)?(?:def|class)\s+")


@dataclass
class ScopeContext:
    name: str
    type: str
    line: int
    column: int

    def to_dict(self):
        return asdict(self)


def scope_context(path, line, col):
    """The class and function scopes enclosing the cursor, outermost first."""
    document = load_document(path)
    document.check_position(line, col)
    tree = parse_tolerant(document.text, cursor=(line, col))
    context = ModuleContext(document.path, "__main__", tree, document.text)
    line_text = document.lines[line - 1]
    byte_col = len(line_text[:col].encode("utf-8"))
    header = _header_at(tree, line, byte_col)
    scope = context.scope_of(header) if header is not None else None
    if scope is None:
        scope = find_scope(context, line, col, line_text)
    result = []
    for current in scope.chain():
        if current.kind in (CLASS, FUNCTION) and isinstance(current.node, _DEFINITIONS):
            result.append(_describe(context, current))
    return list(reversed(result))


def _header_at(tree, line, byte_col):
    """The innermost def/class whose header (after its keyword) contains the cursor.

    The name, parameters and bases of a definition belong to its own context.
    """
    found = None
    for node in ast.walk(tree):
        if not isinstance(node, _DEFINITIONS) or not node.body:
            continue
        if (node.lineno, node.col_offset) < (line, byte_col) and line <= node.body[0].lineno:
            if line < node.body[0].lineno or byte_col < node.body[0].col_offset:
                if found is None or (node.lineno, node.col_offset) > (found.lineno, found.col_offset):
                    found = node
    return found


def _describe(context, scope):
    node = scope.node
    start = char_column(context, node.lineno, node.col_offset)
    text = context.lines[node.lineno - 1] if node.lineno <= len(context.lines) else ""
    match = _DEFINITION_HEADER.match(text, start)
    return ScopeContext(
        name=node.name,
        type=CLASS if isinstance(node, ast.ClassDef) else FUNCTION,
        line=node.lineno,
        column=match.end() if match else start,
    )
