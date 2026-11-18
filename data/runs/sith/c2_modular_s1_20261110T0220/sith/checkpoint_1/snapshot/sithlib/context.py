"""Textual analysis of the cursor position: prefix and completion kind."""
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
