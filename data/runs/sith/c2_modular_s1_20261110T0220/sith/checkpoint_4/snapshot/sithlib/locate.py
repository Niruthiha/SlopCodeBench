"""Finding the innermost scope that contains the cursor."""
import ast

from .scopes import COMPREHENSION, LAMBDA

_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def cursor_indent(line_text, col):
    """Indentation that governs the cursor's block membership."""
    before = line_text[:col]
    if not before.strip():
        return len(before)
    return len(line_text) - len(line_text.lstrip())


def find_scope(context, line, col, line_text):
    """The innermost Scope of `context` enclosing the cursor at (line, col)."""
    byte_col = len(line_text[:col].encode("utf-8"))
    indent = cursor_indent(line_text, col)
    scope = context.root
    for node in _definition_chain(context.tree.body, line, byte_col, indent):
        scope = context.scope_of(node) or scope
    return _innermost_expression_scope(scope, line, byte_col)


def _definition_chain(statements, line, byte_col, indent):
    """def/class nodes whose bodies contain the cursor, outermost first."""
    chain = []
    while True:
        candidate = None
        for statement in statements:
            if statement.lineno <= line:
                candidate = statement
            else:
                break
        if candidate is None:
            return chain
        inside = line <= candidate.end_lineno or indent > candidate.col_offset
        if not inside:
            return chain
        if isinstance(candidate, _DEFINITIONS):
            if not _in_body(candidate, line, byte_col):
                return chain
            chain.append(candidate)
            statements = candidate.body
        else:
            statements = _child_statements(candidate)
            if not statements:
                return chain


def _in_body(node, line, byte_col):
    first = node.body[0]
    if line > _header_end(node):
        return True
    return line == first.lineno and byte_col >= first.col_offset


def _header_end(node):
    parts = []
    if isinstance(node, ast.ClassDef):
        parts = node.bases + [k.value for k in node.keywords]
    else:
        args = node.args
        parts = args.posonlyargs + args.args + args.kwonlyargs + args.defaults
        parts += [d for d in args.kw_defaults if d is not None]
        parts += [a for a in (args.vararg, args.kwarg, node.returns) if a is not None]
    return max([node.lineno] + [getattr(p, "end_lineno", None) or node.lineno for p in parts])


def _child_statements(node):
    children = []
    for field in ("body", "orelse", "finalbody"):
        children += [s for s in getattr(node, field, []) if isinstance(s, ast.stmt)]
    for handler in getattr(node, "handlers", []):
        children += handler.body
    for case in getattr(node, "cases", []):
        children += case.body
    return sorted(children, key=lambda s: (s.lineno, s.col_offset))


def _contains(node, line, byte_col):
    start = (node.lineno, node.col_offset)
    end = (node.end_lineno, node.end_col_offset)
    return start <= (line, byte_col) <= end


def _innermost_expression_scope(scope, line, byte_col):
    """Descend into lambda/comprehension scopes that contain the cursor."""
    while True:
        for child in scope.children:
            if child.kind in (LAMBDA, COMPREHENSION) and _contains(child.node, line, byte_col):
                scope = child
                break
        else:
            return scope
