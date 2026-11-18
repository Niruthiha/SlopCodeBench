"""Cursor context detection.

Secret: how the text before the cursor is lexed to decide whether a bare
name, an attribute, or nothing is being completed, what prefix has been
typed, and which source text forms the receiver of an attribute access.
"""

NAME = "name"
ATTRIBUTE = "attribute"
NONE = "none"

_CLOSERS = {")": "(", "]": "[", "}": "{"}
_STRING_PREFIX_CHARS = set("rRbBuUfF")


class CursorContext:
    def __init__(self, kind, prefix="", receiver=None):
        self.kind = kind
        self.prefix = prefix
        self.receiver = receiver


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
    pos = _skip_space_back(text_before, start)
    if pos > 0 and text_before[pos - 1] == ".":
        dot = pos - 1
        receiver = _receiver_before(text_before, dot)
        if receiver is None:
            return CursorContext(NONE)
        return CursorContext(ATTRIBUTE, prefix, receiver)
    return CursorContext(NAME, prefix)


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
