"""Error-tolerant parsing of Python source into an AST.

Syntax errors are repaired line by line: the offending line is replaced by a
sequence of progressively more conservative candidates (a placeholder name at
the cursor, `pass`, and finally a blank line) until the module parses.  Lines
are never inserted or removed, so AST line numbers match the original file.
"""
import ast
import re
import time
import warnings

# Identifier inserted at the cursor to make incomplete expressions parseable.
# Bindings whose names contain it are ignored by scope analysis.
PLACEHOLDER = "__sith_cursor__"

# After this many seconds of repairs, everything from the error onward is dropped.
_TIME_BUDGET = 1.0
_INDENTATION_ERRORS = ("unindent does not match", "unexpected indent")
_INDENTED_BLOCK = re.compile(r"expected an indented block after .* on line (\d+)")

_CLOSERS = {"(": ")", "[": "]", "{": "}"}
# Keywords that can never appear inside a bracketed expression.
_STATEMENT_KEYWORDS = {
    "def", "class", "return", "import", "pass", "break", "continue", "raise", "del",
    "global", "nonlocal", "assert", "while", "with", "try", "except", "finally", "elif",
}
# Keywords that, at or below the opening line's indentation, start a new statement.
_BLOCK_KEYWORDS = {"if", "for", "else", "async", "from", "match", "case"}
_FIRST_WORD = re.compile(r"[A-Za-z_]\w*")


def parse_tolerant(text, cursor=None):
    """Parse `text`, repairing syntax errors. `cursor` is (line, col) or None."""
    lines = close_brackets(text.replace("\0", " ").split("\n"))
    return _Repairer(lines, cursor).run()


def close_brackets(lines):
    """Close brackets left open when a new statement evidently begins.

    An unclosed bracket otherwise swallows every following line, and the
    parser then blames those (valid) lines instead of the incomplete one.
    """
    lines = list(lines)
    stack = []  # (bracket, line index)
    triple = None
    for index, line in enumerate(lines):
        if stack and triple is None and _starts_statement(line, lines[stack[0][1]]):
            _append_closers(lines, stack, index)
        triple = _scan_brackets(line, stack, triple, index)
    if stack and triple is None:
        _append_closers(lines, stack, len(lines))
    return lines


def _starts_statement(line, opener_line):
    code = line.strip()
    if not code or code.startswith("#"):
        return False
    indent = len(_indent_of(line))
    opener_indent = len(_indent_of(opener_line))
    match = _FIRST_WORD.match(code)
    word = match.group(0) if match else ""
    if word in _STATEMENT_KEYWORDS:
        return True
    if indent <= opener_indent and (word in _BLOCK_KEYWORDS or code.startswith("@")):
        return True
    return indent < opener_indent and code[0] not in ")]}"


def _append_closers(lines, stack, before):
    """Append closers for `stack` to the last code line before index `before`."""
    for index in range(before - 1, stack[0][1] - 1, -1):
        code = strip_comment(lines[index]).rstrip()
        if code.strip():
            lines[index] = code + "".join(_CLOSERS[b] for b, _ in reversed(stack))
            break
    stack.clear()


def _scan_brackets(line, stack, triple, index):
    """Update the bracket stack with `line`; returns the open triple quote, if any."""
    i = 0
    while i < len(line):
        if triple is not None:
            end = line.find(triple, i)
            if end < 0:
                return triple
            i = end + 3
            triple = None
            continue
        char = line[i]
        if char == "#":
            break
        if char in "\"'":
            if line.startswith(char * 3, i):
                triple = char * 3
                i += 3
                continue
            i += 1
            while i < len(line) and line[i] != char:
                i += 2 if line[i] == "\\" else 1
        elif char in _CLOSERS:
            stack.append((char, index))
        elif char in ")]}" and stack and _CLOSERS[stack[-1][0]] == char:
            stack.pop()
        i += 1
    return triple


def strip_comment(line):
    """Remove a trailing `#` comment, ignoring `#` inside string literals."""
    quote = None
    i = 0
    while i < len(line):
        char = line[i]
        if quote:
            if char == "\\":
                i += 1
            elif char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#":
            return line[:i]
        i += 1
    return line


def _neighbour_indent(lines):
    """Indentation of the first code line in `lines`, or None."""
    for line in lines:
        if line.strip() and not line.strip().startswith("#"):
            return len(_indent_of(line))
    return None


def _indent_of(line):
    return line[: len(line) - len(line.lstrip())]


class _Repairer:
    def __init__(self, lines, cursor):
        self.original = lines
        self.state = list(lines)
        self.cursor = cursor
        self.candidates = {}
        self.positions = {}
        self.pass_appended = set()
        self.string_closed = False
        self.truncated = False
        self.deadline = None

    def run(self):
        limit = 4 * len(self.state) + 20
        self.deadline = time.monotonic() + _TIME_BUDGET
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for _ in range(limit):
                try:
                    return ast.parse("\n".join(self.state))
                except (SyntaxError, ValueError) as error:
                    if not self._repair(error):
                        break
        return ast.Module(body=[], type_ignores=[])

    def _repair(self, error):
        count = len(self.state)
        line = getattr(error, "lineno", None) or count
        line = max(1, min(line, count))
        message = str(getattr(error, "msg", ""))
        if "unterminated triple-quoted string" in message and self._close_string(error, line):
            return True
        if not self.truncated and time.monotonic() > self.deadline:
            self._drop_from(line)
            return True
        match = _INDENTED_BLOCK.search(message)
        if match:
            if self._is_cursor_line(line) and self._advance(line):
                return True
            if self._append_pass(int(match.group(1)), line):
                return True
        if any(text in message for text in _INDENTATION_ERRORS) and self._blank(line):
            return True
        if self._advance(line):
            return True
        for previous in range(line - 1, 0, -1):
            if self._advance(previous):
                return True
        return False

    def _is_cursor_line(self, line):
        return self.cursor is not None and self.cursor[0] == line

    def _drop_from(self, line):
        """Give up on the rest of the file: blank every line from `line` on."""
        for index in range(line - 1, len(self.state)):
            self.state[index] = ""
            self._line_candidates(index + 1)
            self.positions[index + 1] = len(self.candidates[index + 1]) - 1
        self.truncated = True

    def _blank(self, line):
        """Jump straight to the blank candidate (indentation cannot be fixed in place)."""
        options = self._line_candidates(line)
        if self.state[line - 1] == "":
            return False
        self.positions[line] = len(options) - 1
        self.state[line - 1] = ""
        return True

    def _close_string(self, error, line):
        """Terminate a triple-quoted string that runs to the end of the file."""
        offset = (getattr(error, "offset", None) or 1) - 1
        quote = self.state[line - 1][offset:offset + 3]
        if quote not in ('"""', "'''") or self.string_closed:
            return False
        self.state[-1] += " " + quote
        self.string_closed = True
        return True

    def _append_pass(self, header_line, error_line):
        """Give a block header with a missing body an inline `pass` body."""
        last = min(max(error_line, header_line), len(self.state))
        for line in range(last, header_line - 1, -1):
            code = strip_comment(self.state[line - 1]).rstrip()
            if code.endswith(":") and line not in self.pass_appended:
                self.state[line - 1] = code + " pass"
                self.pass_appended.add(line)
                return True
        return False

    def _line_candidates(self, line):
        if line not in self.candidates:
            text = self.original[line - 1]
            indent = _indent_of(text)
            options = [text]
            if self._is_cursor_line(line):
                col = min(self.cursor[1], len(text))
                options.append(text[:col] + PLACEHOLDER + text[col:])
                options.append(text[:col] + PLACEHOLDER)
            if self._out_of_place(line, text):
                options.append("")
            header = self._header_replacement(line, text)
            if header:
                options.append(header)
            options += [indent + "pass", ""]
            unique = []
            for option in options:
                if option not in unique:
                    unique.append(option)
            self.candidates[line] = unique
            self.positions[line] = 0
        return self.candidates[line]

    def _out_of_place(self, line, text):
        """True for a line dedented below both its neighbouring code lines."""
        indent = len(_indent_of(text))
        before = _neighbour_indent(reversed(self.original[: line - 1]))
        after = _neighbour_indent(self.original[line:])
        return before is not None and after is not None and indent < min(before, after)

    def _header_replacement(self, line, text):
        """A valid block header for a broken line that is followed by a block.

        Keeping a header lets the indented body that follows still parse,
        instead of failing line by line with "unexpected indent".
        """
        indent = _indent_of(text)
        for following in self.original[line:]:
            if following.strip() and not following.strip().startswith("#"):
                if len(_indent_of(following)) <= len(indent):
                    return None
                break
        else:
            return None
        word = (_FIRST_WORD.match(text.strip()) or [""])[0]
        if word in ("def", "async"):
            return f"{indent}def {PLACEHOLDER}():"
        if word == "class":
            return f"{indent}class {PLACEHOLDER}:"
        return f"{indent}if True:"

    def _advance(self, line):
        """Switch `line` to its next repair candidate; False when exhausted."""
        options = self._line_candidates(line)
        position = self.positions[line]
        while position + 1 < len(options):
            position += 1
            if options[position] != self.state[line - 1]:
                self.positions[line] = position
                self.state[line - 1] = options[position]
                return True
        self.positions[line] = position
        return False
