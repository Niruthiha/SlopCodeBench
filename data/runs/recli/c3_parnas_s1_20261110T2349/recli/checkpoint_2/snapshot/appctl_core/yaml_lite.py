"""YAML reading and writing.

Secret: whether PyYAML is used or the built-in parser for the subset of
YAML that config files need (block mappings and sequences, flow
collections, quoted and plain scalars, comments).
"""

import json
import re

try:  # pragma: no cover - depends on the environment
    import yaml as _yaml
except ImportError:  # pragma: no cover
    _yaml = None


class YamlError(ValueError):
    pass


def load(text):
    """Parse ``text`` and return the resulting Python value."""
    if _yaml is not None:
        try:
            return _yaml.safe_load(text)
        except _yaml.YAMLError as exc:
            raise YamlError(str(exc).replace("\n", " ")) from None
    return _Parser(text).parse()


def dump(data):
    """Serialise a mapping as YAML text."""
    if _yaml is not None:
        return _yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    return json.dumps(data, indent=2) + "\n"


def scalar_line(key, value):
    """A single ``key: value`` line for plain string scalars."""
    return f"{key}: {value}\n"


# --- fallback parser ------------------------------------------------------

_NULLS = {"", "~", "null", "Null", "NULL"}
_TRUES = {"true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"}
_FALSES = {"false", "False", "FALSE", "no", "No", "NO", "off", "Off", "OFF"}
_INT = re.compile(r"^[-+]?(0|[1-9][0-9_]*)$")
_FLOAT = re.compile(r"^[-+]?(\d[\d_]*\.\d*|\.\d+)([eE][-+]?\d+)?$")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "a": "\a", "b": "\b",
            "e": "\x1b", "f": "\f", "v": "\v", " ": " ", "/": "/"}


def _resolve(text):
    text = text.strip()
    if text in _NULLS:
        return None
    if text in _TRUES:
        return True
    if text in _FALSES:
        return False
    if _INT.match(text):
        return int(text.replace("_", ""))
    if _FLOAT.match(text):
        return float(text.replace("_", ""))
    return text


def _strip_comment(line):
    quote = None
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
            elif char == "\\" and quote == '"':
                continue
        elif char in "\"'" and (index == 0 or line[index - 1] in " \t[{,:-"):
            quote = char
        elif char == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index].rstrip()
    return line.rstrip()


def _read_quoted(text, start):
    """Parse a quoted string starting at ``start``; return (value, end)."""
    quote = text[start]
    index = start + 1
    chars = []
    while index < len(text):
        char = text[index]
        if quote == "'" and char == "'":
            if text[index + 1:index + 2] == "'":
                chars.append("'")
                index += 2
                continue
            return "".join(chars), index + 1
        if quote == '"' and char == "\\":
            code = text[index + 1:index + 2]
            width = {"x": 2, "u": 4, "U": 8}.get(code)
            if width:
                try:
                    chars.append(chr(int(text[index + 2:index + 2 + width], 16)))
                except ValueError:
                    raise YamlError("invalid escape sequence") from None
                index += 2 + width
                continue
            chars.append(_ESCAPES.get(code, code))
            index += 2
            continue
        if quote == '"' and char == '"':
            return "".join(chars), index + 1
        chars.append(char)
        index += 1
    raise YamlError("unterminated quoted string")


def _is_seq_item(content):
    return content == "-" or content.startswith("- ")


def _split_key(content):
    """Split a ``key: rest`` line; return (key, rest) or None."""
    if content[:1] in "\"'":
        key, end = _read_quoted(content, 0)
        rest = content[end:].lstrip()
        if not rest.startswith(":"):
            return None
        return key, rest[1:].strip()
    depth = 0
    for index, char in enumerate(content):
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == ":" and depth == 0 and (
                index + 1 == len(content) or content[index + 1] in " \t"):
            return _resolve_key(content[:index]), content[index + 1:].strip()
    return None


def _resolve_key(text):
    value = _resolve(text)
    return text.strip() if value is None or isinstance(value, bool) else value


class _Flow:
    def __init__(self, text):
        self.text = text
        self.pos = 0

    def skip(self):
        while self.pos < len(self.text) and self.text[self.pos] in " \t":
            self.pos += 1

    def peek(self):
        self.skip()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def value(self, stops):
        char = self.peek()
        if char == "[":
            return self.sequence()
        if char == "{":
            return self.mapping()
        if char in "\"'":
            value, self.pos = _read_quoted(self.text, self.pos)
            return value
        start = self.pos
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char in stops:
                break
            if char == ":" and ":" in stops and (
                    self.pos + 1 == len(self.text) or self.text[self.pos + 1] in " ,]}"):
                break
            self.pos += 1
        return _resolve(self.text[start:self.pos])

    def expect(self, char):
        if self.peek() != char:
            raise YamlError(f"expected '{char}' in flow collection")
        self.pos += 1

    def sequence(self):
        self.expect("[")
        items = []
        while self.peek() != "]":
            if not self.peek():
                raise YamlError("unterminated flow sequence")
            items.append(self.value(",]"))
            if self.peek() == ",":
                self.pos += 1
        self.pos += 1
        return items

    def mapping(self):
        self.expect("{")
        result = {}
        while self.peek() != "}":
            if not self.peek():
                raise YamlError("unterminated flow mapping")
            key = self.value(":,}")
            value = None
            if self.peek() == ":":
                self.pos += 1
                value = self.value(",}")
            result[key] = value
            if self.peek() == ",":
                self.pos += 1
        self.pos += 1
        return result


def _inline(text):
    text = text.strip()
    if text[:1] in "[{\"'":
        flow = _Flow(text)
        value = flow.value("")
        if flow.peek():
            raise YamlError(f"unexpected content after value: {text!r}")
        return value
    if text[:1] in "|>&*!%@`":
        if text[:1] != "@":
            raise YamlError(f"unsupported YAML construct: {text!r}")
    return _resolve(text)


class _Parser:
    def __init__(self, text):
        self.lines = []
        for raw in text.splitlines():
            if raw.strip() in ("---", "..."):
                continue
            content = _strip_comment(raw)
            if not content.strip():
                continue
            if "\t" in content[:len(content) - len(content.lstrip())]:
                raise YamlError("tabs are not allowed for indentation")
            stripped = content.lstrip(" ")
            self.lines.append([len(content) - len(stripped), stripped])

    def parse(self):
        if not self.lines:
            return None
        if len(self.lines) == 1 and _split_key(self.lines[0][1]) is None \
                and not _is_seq_item(self.lines[0][1]):
            return _inline(self.lines[0][1])
        value, index = self.block(0, self.lines[0][0])
        if index < len(self.lines):
            raise YamlError(f"unexpected content: {self.lines[index][1]!r}")
        return value

    def block(self, index, indent):
        if _is_seq_item(self.lines[index][1]):
            return self.sequence(index, indent)
        return self.mapping(index, indent)

    def nested(self, index, indent, allow_same_indent_seq):
        """Parse the block following a line ending in ':' or '-'."""
        if index < len(self.lines):
            next_indent, content = self.lines[index]
            if next_indent > indent or (
                    allow_same_indent_seq and next_indent == indent
                    and _is_seq_item(content)):
                return self.block(index, next_indent)
        return None, index

    def sequence(self, index, indent):
        items = []
        while index < len(self.lines):
            line_indent, content = self.lines[index]
            if line_indent != indent or not _is_seq_item(content):
                break
            rest = content[1:].lstrip(" ")
            if not rest:
                value, index = self.nested(index + 1, indent, False)
            elif _split_key(rest) is not None or _is_seq_item(rest):
                self.lines[index] = [indent + len(content) - len(rest), rest]
                value, index = self.block(index, self.lines[index][0])
            else:
                value, index = _inline(rest), index + 1
            items.append(value)
        return items, index

    def mapping(self, index, indent):
        result = {}
        while index < len(self.lines):
            line_indent, content = self.lines[index]
            if line_indent < indent:
                break
            if line_indent > indent:
                raise YamlError(f"bad indentation: {content!r}")
            if _is_seq_item(content):
                break
            pair = _split_key(content)
            if pair is None:
                raise YamlError(f"expected 'key: value', got {content!r}")
            key, rest = pair
            if rest:
                value, index = _inline(rest), index + 1
            else:
                value, index = self.nested(index + 1, indent, True)
            result[key] = value
        return result, index
