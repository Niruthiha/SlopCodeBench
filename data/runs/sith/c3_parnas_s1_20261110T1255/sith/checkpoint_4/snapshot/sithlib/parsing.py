"""Error-tolerant parsing.

Secret: the repair strategy used to turn syntactically broken source into a
syntax tree. Lines keep their numbers, so positions in the returned tree
match positions in the original text.
"""

import ast
import keyword
import re

_ORIGINAL, _PASSED, _BLANKED = 0, 1, 2
_HEADER_RE = re.compile(r"on line (\d+)")
_DEF_RE = re.compile(r"^(\s*)(async\s+)?def\s+([^\W\d]\w*)")
_CLASS_RE = re.compile(r"^(\s*)class\s+([^\W\d]\w*)")
_PARAM_RE = re.compile(r"\s*\*{0,2}\s*([^\W\d]\w*)")
_SALVAGED = 3


def parse_tolerant(text):
    """Return an ``ast.Module`` for ``text``, repairing errors as needed."""
    lines = text.replace("\0", " ").split("\n")
    state = [_ORIGINAL] * len(lines)
    patched_headers = set()
    for _ in range(4 * len(lines) + 20):
        try:
            return ast.parse("\n".join(lines))
        except SyntaxError as exc:
            if not _repair(lines, state, patched_headers, exc):
                break
        except (ValueError, RecursionError, MemoryError):
            break
    return ast.Module(body=[], type_ignores=[])


def _repair(lines, state, patched_headers, exc):
    msg = exc.msg or ""
    if msg.startswith("expected an indented block"):
        match = _HEADER_RE.search(msg)
        if match:
            header = int(match.group(1)) - 1
            if 0 <= header < len(lines) and header not in patched_headers:
                patched_headers.add(header)
                lines[header] = _with_pass_body(lines[header])
                return True
    idx = (exc.lineno or len(lines)) - 1
    idx = max(0, min(idx, len(lines) - 1))
    if msg.startswith("unterminated triple-quoted string") and ("eof", idx) not in patched_headers:
        patched_headers.add(("eof", idx))
        text = lines[idx][max(0, (exc.offset or 1) - 1):]
        quotes = [q for q in ('"""', "'''") if q in text]
        if quotes:
            lines[-1] += min(quotes, key=text.index)
            return True
    while idx >= 0 and (state[idx] == _BLANKED or not lines[idx].strip()):
        idx -= 1
    if idx < 0:
        return False
    if msg.startswith("expected 'except' or 'finally' block"):
        header = _find_try_header(lines, idx)
        if header is not None:
            lines[header] = lines[header][: _indent_width(lines[header])] + "if True:"
            return True
    if msg.startswith("unexpected indent"):
        _blank_block(lines, state, idx)
        return True
    if state[idx] == _ORIGINAL and lines[idx].rstrip().endswith(":"):
        salvaged = _salvage_header(lines[idx])
        if salvaged is not None and salvaged != lines[idx]:
            state[idx] = _SALVAGED
            lines[idx] = salvaged
            return True
    if state[idx] in (_ORIGINAL, _SALVAGED):
        stripped = lines[idx].lstrip()
        indent = lines[idx][: len(lines[idx]) - len(stripped)]
        state[idx] = _PASSED
        lines[idx] = indent + "pass"
    else:
        state[idx] = _BLANKED
        lines[idx] = ""
    return True


def _blank_block(lines, state, idx):
    """Blank an orphaned indented block: line ``idx`` and deeper/equal lines after it."""
    width = _indent_width(lines[idx])
    end = idx
    while end < len(lines) and (not lines[end].strip() or _indent_width(lines[end]) >= width):
        if lines[end].strip():
            state[end] = _BLANKED
            lines[end] = ""
        end += 1


def _find_try_header(lines, idx):
    """The ``try:`` line whose handlers are missing at line ``idx``."""
    limit = _indent_width(lines[idx]) if lines[idx].strip() else None
    for number in range(min(idx, len(lines) - 1), -1, -1):
        stripped = lines[number].strip()
        if not stripped:
            continue
        width = _indent_width(lines[number])
        if stripped.replace(" ", "") == "try:" and (limit is None or width <= limit):
            return number
        if limit is not None and width < limit:
            return None
    return None


def _indent_width(line):
    return len(line) - len(line.lstrip())


def _salvage_header(line):
    """Reduce a broken ``def``/``class`` header to a minimal valid one."""
    match = _DEF_RE.match(line)
    if match:
        params = []
        rest = line[match.end():]
        if rest.lstrip().startswith("("):
            inside = rest[rest.index("(") + 1: rest.rfind(":")]
            for piece in inside.split(","):
                found = _PARAM_RE.match(piece)
                if found and found.group(1) not in params \
                        and not keyword.iskeyword(found.group(1)):
                    params.append(found.group(1))
        return "%s%sdef %s(%s):" % (match.group(1), match.group(2) or "", match.group(3),
                                    ", ".join(params))
    match = _CLASS_RE.match(line)
    if match:
        return "%sclass %s:" % (match.group(1), match.group(2))
    return None


def _with_pass_body(line):
    """Give a block header such as ``if x:`` an inline ``pass`` body."""
    stripped = line.rstrip()
    if stripped.endswith(":"):
        return stripped + " pass"
    colon = stripped.rfind(":")
    if colon >= 0:
        return stripped[: colon + 1] + " pass"
    return stripped
