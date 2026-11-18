"""Cursor context detection.

Secret: how the text before the cursor is lexed to decide whether a bare
name, an attribute, a module in an import statement, a name imported from a
module, or nothing is being completed, what prefix has been typed, and which
source text forms the receiver of an attribute access (or which module an
import refers to); and, for signature help, which call's argument list holds
the cursor and how the arguments typed so far are shaped.
"""

import keyword
import re

NAME = "name"
ATTRIBUTE = "attribute"
IMPORT_MODULE = "import_module"  # ``import a.b|`` / ``from .a|``: module names
IMPORT_NAME = "import_name"      # ``from a import b|``: names inside a module
KEYWORDS = "keywords"            # only the listed keywords fit (``from a imp|``)
NONE = "none"

_DOTTED = r"[^\W\d]\w*(?:\s*\.\s*[^\W\d]\w*)*"
_IMPORT_ITEM_RE = re.compile(r"^(?:(%s)\s*\.\s*)?(\w*)$" % _DOTTED)
_FROM_MODULE_RE = re.compile(r"^from\s*((?:\.\s*)*)(?:(%s)\s*\.\s*)?(\w*)$" % _DOTTED)
_FROM_IMPORT_RE = re.compile(r"^from\s*((?:\.\s*)*)(%s)?\s*(?<![\w])import(?=[\s(])\s*\(?(.*)$"
                             % _DOTTED, re.S)
_FROM_KEYWORD_RE = re.compile(r"^from\s*((?:\.\s*)*)(%s)?\s+(\w*)$" % _DOTTED)

_CLOSERS = {")": "(", "]": "[", "}": "{"}
_STRING_PREFIX_CHARS = set("rRbBuUfF")


# Argument shapes in a call
POSITIONAL = "positional"
KEYWORD = "keyword"
STAR = "star"
DOUBLE_STAR = "double_star"


class CallContext:
    def __init__(self, callee, arguments):
        self.callee = callee        # source text of the called expression
        self.arguments = arguments  # [(shape, keyword name or None)]; the last holds the cursor


def call_context(text_before):
    """The innermost call whose parentheses enclose the cursor, or None."""
    brackets = []
    for index, ch in _code_chars(text_before):
        if ch is None:
            return None  # the cursor is in a comment
        if ch in "([{":
            brackets.append((ch, index))
        elif ch in ")]}" and brackets:
            brackets.pop()
    for ch, index in reversed(brackets):
        if ch == "(":
            callee = _callee_before(text_before, index)
            if callee is not None:
                return CallContext(callee, _arguments(text_before[index + 1:]))
    return None


def _code_chars(text):
    """``(index, char)`` for characters outside strings and comments; a final
    ``(len, None)`` when ``text`` ends inside a comment."""
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "#":
            newline = text.find("\n", i)
            if newline < 0:
                yield n, None
                return
            i = newline
            continue
        if ch in "'\"":
            quote = text[i : i + 3] if text[i : i + 3] in ("'''", '"""') else ch
            i += len(quote)
            while i < n and not text.startswith(quote, i):
                if text[i] == "\\":
                    i += 1
                elif text[i] == "\n" and len(quote) == 1:
                    break
                i += 1
            i += len(quote)
            continue
        yield i, ch
        i += 1


def _callee_before(text, paren):
    """Source text of the expression called by the ``(`` at ``paren``, or None
    when that parenthesis does not start a call."""
    pos = _skip_space_back(text, paren)
    if pos == 0 or not (_is_ident_char(text[pos - 1]) or text[pos - 1] in ")]"):
        return None
    start = _scan_primary(text, pos)
    if start is None or start == pos:
        return None
    if _is_ident_char(text[pos - 1]):
        word = pos
        while word > 0 and _is_ident_char(text[word - 1]):
            word -= 1
        name = text[word:pos]
        if keyword.iskeyword(name) or name[0].isdigit():
            return None
        if re.search(r"\b(def|class)\s+$", text[:start]):
            return None
    return text[start:pos]


def _arguments(text):
    """Shapes of the comma-separated arguments in ``text`` (after the ``(``)."""
    pieces = []
    depth = 0
    start = 0
    for index, ch in _code_chars(text):
        if ch is None:
            break
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            pieces.append(text[start:index])
            start = index + 1
    pieces.append(text[start:])
    return [_argument_shape(piece) for piece in pieces]


def _argument_shape(piece):
    stripped = piece.strip()
    if stripped.startswith("**"):
        return DOUBLE_STAR, None
    if stripped.startswith("*"):
        return STAR, None
    match = re.match(r"([^\W\d]\w*)\s*=(?!=)", stripped)
    if match:
        return KEYWORD, match.group(1)
    return POSITIONAL, None


class CursorContext:
    def __init__(self, kind, prefix="", receiver=None, module="", level=0, words=()):
        self.kind = kind
        self.prefix = prefix
        self.receiver = receiver
        self.module = module  # import contexts: dotted module name (may be "")
        self.level = level    # import contexts: leading dots of a relative import
        self.words = list(words)


def analyze(text_before):
    """Classify the cursor at the end of ``text_before``."""
    if _inside_string_or_comment(text_before):
        return CursorContext(NONE)
    end = len(text_before)
    start = end
    while start > 0 and _is_ident_char(text_before[start - 1]):
        start -= 1
    prefix = text_before[start:end]
    if prefix and prefix[0].isdigit():
        return CursorContext(NONE)
    statement = _import_statement(text_before)
    if statement is not None:
        return _import_context(statement)
    pos = _skip_space_back(text_before, start)
    if pos > 0 and text_before[pos - 1] == ".":
        dot = pos - 1
        receiver = _receiver_before(text_before, dot)
        if receiver is None:
            return CursorContext(NONE)
        return CursorContext(ATTRIBUTE, prefix, receiver)
    return CursorContext(NAME, prefix)


def _import_statement(text):
    """The current statement up to the cursor if it is an import, else None."""
    start = _statement_start(text)
    statement = text[start:].replace("\\\n", " ")
    statement = re.sub(r"#[^\n]*", "", statement)
    statement = statement.lstrip()
    if re.match(r"(import|from)\b", statement) and statement not in ("import", "from"):
        return statement
    return None


def _statement_start(text):
    """Index where the logical statement containing the end of ``text`` begins."""
    start = 0
    depth = 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "#":
            newline = text.find("\n", i)
            if newline < 0:
                break
            i = newline
            continue
        if ch in "'\"":
            quote = text[i : i + 3] if text[i : i + 3] in ("'''", '"""') else ch
            i += len(quote)
            while i < n and not text.startswith(quote, i):
                if text[i] == "\\":
                    i += 1
                elif text[i] == "\n" and len(quote) == 1:
                    break
                i += 1
            i += len(quote)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == "\n":
            if i > 0 and text[i - 1] == "\\":
                pass
            elif depth == 0:
                start = i + 1
        elif ch == ";" and depth == 0:
            start = i + 1
        elif ch == ":" and depth == 0 and _ends_block_header(text, start, i):
            start = i + 1
        i += 1
    return start


def _ends_block_header(text, start, colon):
    """Whether ``colon`` ends a compound statement header (``if x: import y``)."""
    head = text[start:colon].lstrip()
    return bool(re.match(r"(if|elif|else|while|for|try|except|finally|with|def|class|async)\b",
                         head))


def _import_context(statement):
    """Classify the cursor at the end of an ``import``/``from`` statement."""
    if statement.startswith("import"):
        items = statement[len("import"):]
        if items and not items[0].isspace():
            return CursorContext(NONE)
        last = items.split(",")[-1].strip()
        match = _IMPORT_ITEM_RE.match(last)
        if not match:
            return CursorContext(NONE)
        return CursorContext(IMPORT_MODULE, match.group(2), module=_dotted(match.group(1)))
    match = _FROM_IMPORT_RE.match(statement)
    if match:
        last = match.group(3).split(",")[-1].strip()
        if not re.match(r"^\w*$", last) or (match.group(3).count("(") > 0):
            return CursorContext(NONE)
        level = match.group(1).count(".")
        module = _dotted(match.group(2))
        if not module and not level:
            return CursorContext(NONE)
        return CursorContext(IMPORT_NAME, last, module=module, level=level)
    match = _FROM_MODULE_RE.match(statement)
    if match and (match.group(1) or statement[len("from"):][:1].isspace()):
        return CursorContext(IMPORT_MODULE, match.group(3), module=_dotted(match.group(2)),
                             level=match.group(1).count("."))
    match = _FROM_KEYWORD_RE.match(statement)
    if match and (match.group(1) or match.group(2)):
        return CursorContext(KEYWORDS, match.group(3), words=["import"])
    return CursorContext(NONE)


def _dotted(text):
    return re.sub(r"\s+", "", text or "")


def _is_ident_char(ch):
    return ch == "_" or ch.isalnum()


def _skip_space_back(text, pos):
    while pos > 0 and text[pos - 1] in " \t":
        pos -= 1
    return pos


def _inside_string_or_comment(text):
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "#":
            newline = text.find("\n", i)
            if newline < 0:
                return True
            i = newline + 1
        elif ch in "'\"":
            quote = text[i : i + 3] if text[i : i + 3] in ("'''", '"""') else ch
            i += len(quote)
            closed = False
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text.startswith(quote, i):
                    i += len(quote)
                    closed = True
                    break
                if text[i] == "\n" and len(quote) == 1:
                    break
                i += 1
            if not closed and i >= n:
                return True
        else:
            i += 1
    return False


def _receiver_before(text, dot):
    """Source text of the primary expression ending just before ``dot``."""
    if dot > 0 and text[dot - 1] == ".":
        return None
    pos = _skip_space_back(text, dot)
    begin = _scan_primary(text, pos)
    if begin is None or begin == pos:
        return None
    receiver = text[begin:pos].strip()
    if receiver and (receiver[0].isdigit() and receiver.replace("_", "").isdigit()):
        return None
    return receiver


def _scan_primary(text, pos):
    """Scan one primary (atom plus trailers) backwards; return its start."""
    while True:
        if pos == 0:
            return None
        ch = text[pos - 1]
        if ch in _CLOSERS:
            opener = _match_open(text, pos - 1)
            if opener is None:
                return None
            pos = opener
            if pos > 0 and (_is_ident_char(text[pos - 1]) or text[pos - 1] in _CLOSERS
                            or text[pos - 1] in "'\""):
                continue
            return _after_dot_chain(text, pos)
        if ch in "'\"":
            start = _match_string_start(text, pos)
            if start is None:
                return None
            return start
        if _is_ident_char(ch):
            while pos > 0 and _is_ident_char(text[pos - 1]):
                pos -= 1
            return _after_dot_chain(text, pos)
        return None


def _after_dot_chain(text, pos):
    """If the atom starting at ``pos`` is preceded by a dot, keep scanning."""
    before = _skip_space_back(text, pos)
    if before > 0 and text[before - 1] == "." and not (before > 1 and text[before - 2] == "."):
        inner = _scan_primary(text, _skip_space_back(text, before - 1))
        return inner if inner is not None else pos
    return pos


def _match_open(text, close_index):
    depth = 0
    i = close_index
    while i >= 0:
        ch = text[i]
        if ch in "'\"":
            start = _match_string_start(text, i + 1)
            if start is None:
                return None
            i = start - 1
            continue
        if ch in _CLOSERS:
            depth += 1
        elif ch in "([{":
            depth -= 1
            if depth == 0:
                return i
        i -= 1
    return None


def _match_string_start(text, end):
    """Given ``text[end - 1]`` is a closing quote, find the literal's start."""
    quote_char = text[end - 1]
    triple = quote_char * 3
    if end >= 3 and text[end - 3 : end] == triple:
        found = text.rfind(triple, 0, end - 3)
        start = found if found >= 0 else None
    else:
        i = end - 2
        start = None
        while i >= 0:
            if text[i] == quote_char and not _escaped(text, i):
                start = i
                break
            if text[i] == "\n":
                break
            i -= 1
    if start is None:
        return None
    head = start
    while head > 0 and start - head < 2 and text[head - 1] in _STRING_PREFIX_CHARS:
        head -= 1
    if head < start and not (head > 0 and _is_ident_char(text[head - 1])):
        return head
    return start


def _escaped(text, i):
    count = 0
    while i - 1 - count >= 0 and text[i - 1 - count] == "\\":
        count += 1
    return count % 2 == 1
