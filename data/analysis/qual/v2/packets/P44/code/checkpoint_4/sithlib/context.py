"""Textual analysis of the cursor position: prefix and completion kind."""
import re
from dataclasses import dataclass

NAME = "name"
ATTRIBUTE = "attribute"
NONE = "none"

_OPENERS = {")": "(", "]": "[", "}": "{"}
_STRING_PREFIX_CHARS = "rRbBuUfF"


@dataclass
class CursorContext:
    """What kind of completion is requested and what has been typed so far."""

    kind: str
    prefix: str = ""
    receiver: str = ""


def is_identifier_char(char):
    return char == "_" or char.isalnum()


def analyze(text_before_cursor):
    """Classify the completion request from the source text before the cursor."""
    end = len(text_before_cursor)
    start = end
    while start > 0 and is_identifier_char(text_before_cursor[start - 1]):
        start -= 1
    prefix = text_before_cursor[start:]
    if prefix and prefix[0].isdigit():
        return CursorContext(NONE, prefix)

    before = text_before_cursor[:start]
    if not before.endswith("."):
        return CursorContext(NAME, prefix)

    receiver = extract_receiver(before[:-1])
    if not receiver or receiver.isdigit() or receiver.endswith("."):
        return CursorContext(NONE, prefix)
    return CursorContext(ATTRIBUTE, prefix, receiver)


def extract_receiver(text):
    """Return the expression text that ends at the end of `text`, or None."""
    i = len(text)
    while i > 0:
        char = text[i - 1]
        if char in _OPENERS:
            opener = _match_open(text, i - 1)
            if opener is None:
                return None
            i = opener
            continue
        if is_identifier_char(char):
            while i > 0 and is_identifier_char(text[i - 1]):
                i -= 1
            if i > 0 and text[i - 1] == ".":
                i -= 1
                continue
            break
        if char in "\"'":
            start = _string_start(text, i - 1)
            if start is None:
                return None
            i = start
            while i > 0 and text[i - 1] in _STRING_PREFIX_CHARS:
                i -= 1
            break
        break
    return text[i:].strip()


def _match_open(text, close_index):
    """Index of the bracket opening the one at `close_index`, scanning backwards."""
    stack = [text[close_index]]
    i = close_index - 1
    while i >= 0:
        char = text[i]
        if char in "\"'":
            start = _string_start(text, i)
            if start is None:
                return None
            i = start - 1
            continue
        if char in _OPENERS:
            stack.append(char)
        elif char in "([{":
            if _OPENERS[stack[-1]] != char:
                return None
            stack.pop()
            if not stack:
                return i
        i -= 1
    return None


def _string_start(text, end_index):
    """Index of the opening quote of the string literal ending at `end_index`."""
    quote = text[end_index]
    if end_index >= 2 and text[end_index - 2:end_index + 1] == quote * 3:
        start = text.rfind(quote * 3, 0, end_index - 2)
        return None if start < 0 else start
    i = end_index - 1
    while i >= 0:
        if text[i] == quote and (i == 0 or text[i - 1] != "\\"):
            return i
        if text[i] == "\n":
            return None
        i -= 1
    return None


# -- import statements --------------------------------------------------------------

IMPORT_MODULE = "import-module"
IMPORT_NAME = "import-name"
IMPORT_KEYWORD = "import-keyword"
IMPORT_NOTHING = "import-nothing"

_STATEMENT_START = re.compile(r"\s*(?:from|import)\b")
_DOTTED = r"((?:\w+\s*\.\s*)*)(\w*)"
_IMPORT = re.compile(r"\s*import\s+(.*)", re.S)
_FROM = re.compile(r"\s*from\s+(.*)", re.S)
_FROM_NAMES = re.compile(r"(\.*)\s*([\w.\s]*?)\s*\bimport\s+(.*)", re.S)
_FROM_KEYWORD = re.compile(r"(\.*)\s*(\w+(?:\s*\.\s*\w+)*|)\s+(\w*)", re.S)
_FROM_MODULE = re.compile(r"(\.*)\s*" + _DOTTED, re.S)
_ITEM = re.compile(_DOTTED, re.S)
_NAME = re.compile(r"(\w*)")


@dataclass
class ImportContext:
    """A cursor inside an import statement.

    `module` is the dotted module (relative to `level` leading dots) whose
    submodules or names are completed; `prefix` is what has been typed.
    """

    kind: str
    prefix: str = ""
    module: str = ""
    level: int = 0


def analyze_import(text_before_cursor):
    """An ImportContext when the cursor is inside an import statement, else None."""
    statement = _import_statement(text_before_cursor)
    if statement is None:
        return None
    if re.fullmatch(r"\s*(?:import|from)", statement):
        return None  # still typing the keyword itself
    match = _IMPORT.fullmatch(statement)
    if match:
        item = match.group(1).split(",")[-1].lstrip()
        found = _ITEM.fullmatch(item)
        if not found:
            return ImportContext(IMPORT_NOTHING)
        return ImportContext(IMPORT_MODULE, found.group(2), _dotted(found.group(1)))
    match = _FROM.fullmatch(statement)
    if not match:
        return ImportContext(IMPORT_NOTHING)
    rest = match.group(1)
    found = _FROM_NAMES.fullmatch(rest)
    if found and (found.group(1) or found.group(2).strip()):
        module = re.sub(r"\s+", "", found.group(2))
        item = found.group(3).split(",")[-1].strip()
        name = _NAME.fullmatch(item)
        if not name or not (module.replace(".", "").isidentifier() or not module):
            return ImportContext(IMPORT_NOTHING)
        return ImportContext(IMPORT_NAME, name.group(1), module, len(found.group(1)))
    found = _FROM_KEYWORD.fullmatch(rest)
    if found and (found.group(1) or found.group(2)):
        return ImportContext(IMPORT_KEYWORD, found.group(3))
    found = _FROM_MODULE.fullmatch(rest)
    if found:
        return ImportContext(IMPORT_MODULE, found.group(3), _dotted(found.group(2)),
                             len(found.group(1)))
    return ImportContext(IMPORT_NOTHING)


def _dotted(text):
    """`a . b .` -> `a.b`."""
    return ".".join(part for part in re.sub(r"\s+", "", text).split(".") if part)


def _import_statement(text):
    """The text of the import statement the cursor is in, joined onto one line, or None."""
    lines = text.split("\n")
    current = len(lines) - 1
    lines[current] = _last_simple_statement(lines[current])
    for start in range(current, max(-1, current - 100), -1):
        if _STATEMENT_START.match(lines[start]):
            if not _continues(lines[start:current]):
                return None
            joined = " ".join(_code(line).rstrip().rstrip("\\") for line in lines[start:current])
            joined = (joined + " " + lines[current]) if start < current else lines[current]
            return joined.replace("(", " ").replace(")", " ")
    return None


def _code(line):
    """`line` without a trailing comment."""
    quote = None
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#":
            return line[:index]
    return line


def _last_simple_statement(line):
    """The part of `line` after its last top-level `;`."""
    depth = 0
    quote = None
    start = 0
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == ";" and depth <= 0:
            start = index + 1
    return line[start:]


def _continues(lines):
    """True when each of `lines` continues onto the next (open bracket or backslash)."""
    depth = 0
    for line in lines:
        code = _code(line)
        depth += code.count("(") - code.count(")")
        if depth <= 0 and not code.rstrip().endswith("\\"):
            return False
    return True
