"""Syntax error reporting (``errors``).

Secret: how syntax errors are found (the compiler's first error, then further
ones after neutralizing each offending line), which follow-on errors caused by
that neutralizing are suppressed, and how each is described (positions and
message).
"""

import re

from .source import SourceFile

_LIMIT = 50
_HEADER = re.compile(r"^(\s*)(async\s+)?(def|class|if|elif|else|for|while|with|try|except|"
                     r"finally|match|case)\b")


def errors(path):
    """Syntax errors of the file: dicts of line, column, until_line, until_column
    and message, in file order."""
    source = SourceFile(path)
    lines = source.lines()
    original = list(lines)
    touched = set()
    found = {}
    for _ in range(_LIMIT):
        error = _first_error("\n".join(lines))
        if error is None:
            break
        record = _record(error, original)
        index = record["line"] - 1
        follow_on = _follow_on(error, index, touched, lines)
        if not follow_on:
            found.setdefault((record["line"], record["column"]), record)
        if not _neutralize(lines, index, touched, error):
            break
    return [found[key] for key in sorted(found)]


def _first_error(text):
    try:
        compile(text, "<file>", "exec", dont_inherit=True, flags=0x400)  # PyCF_ONLY_AST
    except SyntaxError as exc:
        return exc
    except (ValueError, RecursionError, MemoryError) as exc:
        error = SyntaxError(str(exc))
        error.lineno, error.offset = 1, 1
        return error
    return None


def _record(error, lines):
    count = max(1, len(lines))
    line = min(max(1, error.lineno or count), count)
    text = lines[line - 1] if line - 1 < len(lines) else ""
    column = max(0, (error.offset or 1) - 1)
    column = min(column, len(text))
    until_line = getattr(error, "end_lineno", None) or line
    end_offset = getattr(error, "end_offset", None)
    until_line = min(max(until_line, line), count)
    if end_offset is None or end_offset <= 0:
        until_column = min(column + 1, len(text)) if until_line == line else column
    else:
        end_text = lines[until_line - 1] if until_line - 1 < len(lines) else ""
        until_column = min(max(0, end_offset - 1), len(end_text))
    if until_line == line and until_column < column:
        until_column = column
    message = "%s: %s" % (type(error).__name__, error.msg or "invalid syntax")
    return {"line": line, "column": column, "until_line": until_line,
            "until_column": until_column, "message": message}


def _follow_on(error, index, touched, lines):
    """Whether ``error`` only results from an earlier neutralized line."""
    msg = error.msg or ""
    if index in touched:
        return True
    if msg.startswith(("unexpected indent", "unindent does not match",
                       "expected an indented block")):
        previous = index - 1
        while previous >= 0 and not lines[previous].strip():
            previous -= 1
        return previous in touched
    return False


def _neutralize(lines, index, touched, error):
    """Make line ``index`` harmless; False when no progress is possible."""
    if not 0 <= index < len(lines):
        return False
    msg = error.msg or ""
    if msg.startswith("expected an indented block"):
        match = re.search(r"on line (\d+)", msg)
        header = int(match.group(1)) - 1 if match else index - 1
        if 0 <= header < len(lines) and ("body", header) not in touched:
            touched.add(("body", header))
            touched.add(header)
            lines[header] = lines[header].rstrip() + " pass"
            return True
    if msg.startswith("unterminated triple-quoted string") or msg.endswith("was never closed"):
        return False
    text = lines[index]
    indent = text[:len(text) - len(text.lstrip())]
    if lines[index].strip() in ("pass", "if True:", "") and index in touched:
        if lines[index].strip() == "":
            return False
        lines[index] = ""
        return True
    touched.add(index)
    if msg.startswith(("unexpected indent", "unindent does not match")):
        lines[index] = ""
        return True
    if _HEADER.match(text) and text.rstrip().endswith(":") or \
            _HEADER.match(text) and _opens_block(lines, index):
        lines[index] = indent + "if True:"
    else:
        lines[index] = indent + "pass"
    return True


def _opens_block(lines, index):
    width = len(lines[index]) - len(lines[index].lstrip())
    for following in lines[index + 1:]:
        if following.strip():
            return len(following) - len(following.lstrip()) > width
    return False
