#!/usr/bin/env python3
"""appctl - a hierarchical command-line tool.

Usage:
    python appctl.py [@<alias>] [<command>] [<subcommand>] [<args>] [--<flags>]
"""

import csv
import datetime
import io
import json
import os
import re
import sys
import time

VERSION = "1.0.0"
PROG = "appctl"
STRICT_ENV = "APPCTL_STRICT_ARGS_MODE"
SUGGESTION_THRESHOLD = 2


# ---------------------------------------------------------------------------
# Errors and output helpers
# ---------------------------------------------------------------------------

class AppctlExit(Exception):
    """Raised to terminate the program with a given exit code."""

    def __init__(self, code=0):
        super().__init__(code)
        self.code = code


class SynopsisError(ValueError):
    """Raised when a synopsis string contains a malformed token."""


class Runtime:
    quiet = False
    debug = False
    debug_group = None
    config = {}
    aliases = {}
    global_config_path = None
    project_config_path = None
    start_time = time.time()


# ANSI color codes for message prefixes.
COLORS = {
    "Error": "\033[31;1m",
    "Warning": "\033[33;1m",
    "Success": "\033[32;1m",
    "Debug": "\033[34;1m",
}
COLOR_RESET = "\033[0m"
BOX_COLOR = "\033[37;41;1m"
LOG_DELIMITER = "=" * 80
STDIN_TIMEOUT = 1.0
PROMPT_TIMEOUT = 2.0
SENSITIVE_KEY_RE = re.compile(r"pass|secret|token", re.IGNORECASE)


def use_color():
    """Return whether colorized output is enabled (``color`` config: auto/true/false)."""
    value = Runtime.config.get("color", "auto")
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on", "always"):
            value = True
        elif lowered in ("false", "0", "no", "off", "never"):
            value = False
    if value is True:
        return True
    if value is False or value is None:
        return False
    if os.name == "nt" or sys.platform.startswith("win"):
        return False
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def colorize_prefix(label):
    """Return ``<label>:`` colorized according to its message category."""
    text = label + ":"
    if not use_color():
        return text
    return COLORS[label.split()[0]] + text + COLOR_RESET


# ---------------------------------------------------------------------------
# File logging
# ---------------------------------------------------------------------------

class FileLog:
    enabled = True


def log_file_path():
    return os.path.join(root_dir(), "logs", "%s.log" % PROG)


def log_timestamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_log(text, delimiter=False):
    """Append ``text`` to the log file; every line gets a UTC timestamp."""
    if not FileLog.enabled:
        return
    stamp = log_timestamp()
    lines = [LOG_DELIMITER] if delimiter else []
    lines.extend("[%s] %s" % (stamp, line) for line in str(text).split("\n"))
    try:
        path = log_file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except (OSError, ValueError):
        pass


def redact_argv(argv):
    """Hide the values of password-like options before they reach the log file."""
    redacted = []
    for token in argv:
        parsed = parse_token(token)
        if parsed is not None and isinstance(parsed[1], str) and SENSITIVE_KEY_RE.search(parsed[0]):
            token = "--%s=[REDACTED]" % parsed[0]
        redacted.append(token)
    return redacted


def log_invocation(argv):
    write_log("Command: %s" % " ".join([PROG] + redact_argv(argv)), delimiter=True)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def out(text=""):
    sys.stdout.write(text + "\n")


def success(message):
    if not Runtime.quiet:
        out(colorize_prefix("Success") + " " + message)


def log(message, sensitive=False):
    """Informational output: STDOUT plus the log file (unless sensitive)."""
    if Runtime.quiet:
        return
    out(message)
    if not sensitive:
        write_log(message)


def warning(message):
    sys.stderr.write(colorize_prefix("Warning") + " " + message + "\n")
    write_log("Warning: " + message)


def debug(message, group=None):
    if not Runtime.debug:
        return
    if Runtime.debug_group and group != Runtime.debug_group:
        return
    label = "Debug (%s)" % group if Runtime.debug_group else "Debug"
    text = "%s (%.3fs)" % (message, time.time() - Runtime.start_time)
    sys.stderr.write(colorize_prefix(label) + " " + text + "\n")
    write_log("%s: %s" % (label, text))


def error_box(lines):
    """Write ``lines`` to STDERR inside a highlighted box."""
    lines = [line.replace("\t", "    ") for line in lines]
    width = max(len(line) for line in lines)
    border = "+" + "-" * (width + 2) + "+"
    rows = [border] + ["| %s |" % line.ljust(width) for line in lines] + [border]
    if use_color():
        rows = [BOX_COLOR + row + COLOR_RESET for row in rows]
    sys.stderr.write("\n".join(rows) + "\n")


def error(message, code=1, sensitive=False, box=None):
    """Report an error and exit. Sensitive errors are never written to the log file."""
    message = str(message)
    lines = message.split("\n")
    if box is None:
        box = len(lines) > 1
    if box:
        error_box(["Error: " + lines[0]] + lines[1:])
    else:
        sys.stderr.write(colorize_prefix("Error") + " " + message + "\n")
    if not sensitive:
        write_log("Error: " + message)
    raise AppctlExit(code)


# ---------------------------------------------------------------------------
# User input
# ---------------------------------------------------------------------------

def _stdin_ready(timeout):
    """Return False when STDIN is a pipe that stays empty for ``timeout`` seconds."""
    if os.name == "nt":
        return True
    import select
    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
    except (OSError, ValueError, TypeError):
        return True
    return bool(ready)


def _stdin_is_tty():
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def prompt(question):
    """Display ``question``, read one line from STDIN, return it lowercased and trimmed."""
    sys.stdout.write(question)
    sys.stdout.flush()
    if sys.stdin is None:
        return ""
    if not _stdin_is_tty() and not _stdin_ready(PROMPT_TIMEOUT):
        return ""
    try:
        answer = sys.stdin.readline()
    except (OSError, ValueError):
        answer = ""
    if not answer.endswith("\n") or not _stdin_is_tty():
        sys.stdout.write("\n")
    return answer.strip().lower()


def confirm(question, assoc=None):
    """Ask a ``[y/n]`` question; ``--yes`` auto-confirms. Returns True when confirmed."""
    if assoc and assoc.get("yes"):
        return True
    if prompt(question + " [y/n] ") != "y":
        warning("Operation cancelled.")
        return False
    return True


def read_stdin():
    """Read all of STDIN for a missing positional argument (None when unavailable)."""
    if sys.stdin is None or _stdin_is_tty():
        return None
    if not _stdin_ready(STDIN_TIMEOUT):
        return None
    try:
        data = sys.stdin.read()
    except (OSError, ValueError):
        return None
    data = data.rstrip("\r\n")
    return data if data != "" else None


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

# Curated synonyms for common command-name variants. A synonym is only
# suggested when the target is actually registered among the candidates.
SYNONYMS = {
    "add": "create",
    "check": "check-update",
    "clear": "flush",
    "conf": "config",
    "configure": "config",
    "decrement": "decr",
    "del": "delete",
    "destroy": "delete",
    "directory": "dir",
    "erase": "delete",
    "exec": "eval",
    "exec-file": "eval-file",
    "increment": "incr",
    "info": "get",
    "lang": "locale",
    "language": "locale",
    "ls": "list",
    "make": "create",
    "new": "create",
    "number": "count",
    "regen": "regenerate",
    "remove": "delete",
    "rep": "replace",
    "repl": "replace",
    "rm": "delete",
    "settings": "config",
    "show": "get",
    "trash": "delete",
    "v": "version",
    "ver": "version",
}


def levenshtein(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def sort_key(name):
    return (name.lower(), name)


def get_suggestion(word, candidates, threshold=SUGGESTION_THRESHOLD, synonyms=True):
    """Return the closest candidate to ``word`` or None (deterministic)."""
    candidates = sorted(set(candidates), key=sort_key)
    if not candidates:
        return None
    lowered = word.lower()
    if synonyms:
        target = SYNONYMS.get(lowered)
        if target is not None and target in candidates:
            return target
    best, best_dist = None, None
    for candidate in candidates:
        dist = levenshtein(lowered, candidate.lower())
        if best_dist is None or dist < best_dist:
            best, best_dist = candidate, dist
    if best_dist is not None and best_dist <= threshold:
        return best
    return None


# ---------------------------------------------------------------------------
# YAML (the subset used by config files)
# ---------------------------------------------------------------------------

class YamlError(ValueError):
    """Raised when a YAML document cannot be parsed."""


_YAML_ESCAPES = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n",
                 "v": "\v", "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"',
                 "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0"}
_YAML_INT = re.compile(r"[-+]?[0-9]+")
_YAML_FLOAT = re.compile(r"[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?")
_YAML_BLOCK_SCALAR = re.compile(r"[|>](?:[+-]?[1-9]?|[1-9][+-])")


def _yaml_strip_comment(line):
    """Remove a trailing ``# comment`` that is not inside a quoted scalar."""
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote == "'":
            if ch == "'":
                if line[i + 1:i + 2] == "'":
                    i += 1
                else:
                    quote = None
        elif quote == '"':
            if ch == "\\":
                i += 1
            elif ch == '"':
                quote = None
        elif ch in "'\"" and (i == 0 or line[i - 1] in " \t[{,:-"):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
        i += 1
    return line.rstrip()


def _yaml_resolve(text):
    text = text.strip()
    if text in ("", "~") or text.lower() == "null":
        return None
    lowered = text.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if _YAML_INT.fullmatch(text):
        return int(text)
    if _YAML_FLOAT.fullmatch(text):
        return float(text)
    return text


class _FlowParser:
    """Parse quoted scalars and flow collections (``[...]`` / ``{...}``)."""

    def __init__(self, text):
        self.text = text
        self.pos = 0

    def parse_all(self):
        value = self.node(top=True)
        self.ws()
        if self.pos != len(self.text):
            raise YamlError("Unexpected content: %s" % self.text[self.pos:])
        return value

    def ws(self):
        while self.pos < len(self.text) and self.text[self.pos] in " \t\n":
            self.pos += 1

    def peek(self):
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def node(self, top=False, key=False):
        self.ws()
        ch = self.peek()
        if ch == "[":
            return self.sequence()
        if ch == "{":
            return self.mapping()
        if ch == '"':
            return self.double_quoted()
        if ch == "'":
            return self.single_quoted()
        return self.plain(top, key)

    def sequence(self):
        self.pos += 1
        items = []
        while True:
            self.ws()
            if self.peek() == "]":
                self.pos += 1
                return items
            if not self.peek():
                raise YamlError("Unterminated flow sequence")
            items.append(self.node())
            self.ws()
            if self.peek() == ",":
                self.pos += 1
            elif self.peek() != "]":
                raise YamlError("Expected ',' or ']' in flow sequence")

    def mapping(self):
        self.pos += 1
        result = {}
        while True:
            self.ws()
            if self.peek() == "}":
                self.pos += 1
                return result
            if not self.peek():
                raise YamlError("Unterminated flow mapping")
            key = self.node(key=True)
            self.ws()
            value = None
            if self.peek() == ":":
                self.pos += 1
                self.ws()
                if self.peek() not in (",", "}"):
                    value = self.node()
            result["" if key is None else str(key)] = value
            self.ws()
            if self.peek() == ",":
                self.pos += 1
            elif self.peek() != "}":
                raise YamlError("Expected ',' or '}' in flow mapping")

    def double_quoted(self):
        self.pos += 1
        chars = []
        text = self.text
        while self.pos < len(text):
            ch = text[self.pos]
            if ch == '"':
                self.pos += 1
                return "".join(chars)
            if ch == "\\":
                esc = text[self.pos + 1:self.pos + 2]
                if esc in ("x", "u", "U"):
                    size = {"x": 2, "u": 4, "U": 8}[esc]
                    digits = text[self.pos + 2:self.pos + 2 + size]
                    try:
                        chars.append(chr(int(digits, 16)))
                    except ValueError:
                        raise YamlError("Invalid escape sequence")
                    self.pos += 2 + size
                    continue
                if esc == "\n":
                    self.pos += 2
                    continue
                if esc not in _YAML_ESCAPES:
                    raise YamlError("Invalid escape sequence")
                chars.append(_YAML_ESCAPES[esc])
                self.pos += 2
                continue
            chars.append(ch)
            self.pos += 1
        raise YamlError("Unterminated double-quoted scalar")

    def single_quoted(self):
        self.pos += 1
        chars = []
        text = self.text
        while self.pos < len(text):
            ch = text[self.pos]
            if ch == "'":
                if text[self.pos + 1:self.pos + 2] == "'":
                    chars.append("'")
                    self.pos += 2
                    continue
                self.pos += 1
                return "".join(chars)
            chars.append(ch)
            self.pos += 1
        raise YamlError("Unterminated single-quoted scalar")

    def plain(self, top, key):
        if top:
            value = self.text[self.pos:]
            self.pos = len(self.text)
            return _yaml_resolve(value)
        start = self.pos
        text = self.text
        while self.pos < len(text):
            ch = text[self.pos]
            if ch in ",[]{}":
                break
            if ch == ":" and (key or text[self.pos + 1:self.pos + 2] in ("", " ", ",", "}", "]")):
                break
            self.pos += 1
        return _yaml_resolve(text[start:self.pos])


def _yaml_inline(text):
    """Parse a single-line (or joined multi-line flow) YAML value."""
    text = text.strip()
    if text.startswith(("&", "!")):
        text = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
    if not text or text[0] not in "[{\"'":
        return _yaml_resolve(text)
    return _FlowParser(text).parse_all()


def _yaml_split_key(content):
    """Split ``key: value`` into (key, value-text), or return None."""
    if not content or content[0] in "[{" or content.startswith(("- ", "? ")) or content == "-":
        return None
    if content[0] in "\"'":
        parser = _FlowParser(content)
        try:
            key = parser.double_quoted() if content[0] == '"' else parser.single_quoted()
        except YamlError:
            return None
        rest = content[parser.pos:].lstrip(" \t")
        if rest == ":" or rest.startswith((": ", ":\t")):
            return key, rest[1:].strip()
        return None
    for match in re.finditer(r":(?=\s|$)", content):
        key = content[:match.start()].rstrip()
        if key:
            return key, content[match.end():].strip()
    return None


def _yaml_flow_balance(text):
    depth = 0
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote and not (quote == '"' and text[i - 1] == "\\"):
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
    return depth


class _YamlParser:
    def __init__(self, text):
        self.lines = text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(2).split("\n")
        self.index = 0

    def peek(self):
        """Return (indent, content) of the next meaningful line, or None."""
        while self.index < len(self.lines):
            stripped = _yaml_strip_comment(self.lines[self.index])
            content = stripped.strip()
            if not content or content.startswith("%") or (
                    stripped == stripped.lstrip() and content in ("---", "...")):
                self.index += 1
                continue
            if stripped.startswith("--- "):
                stripped = "    " + stripped[4:]
                self.lines[self.index] = stripped
            return len(stripped) - len(stripped.lstrip(" ")), stripped.strip()
        return None

    def parse(self):
        head = self.peek()
        if head is None:
            return None
        value = self.block(head[0])
        if self.peek() is not None:
            raise YamlError("Unexpected content on line %d" % (self.index + 1))
        return value

    def block(self, indent):
        ind, content = self.peek()
        if content == "-" or content.startswith("- "):
            return self.sequence(ind)
        if _yaml_split_key(content) is not None:
            return self.mapping(ind)
        self.index += 1
        return self.scalar(content, indent - 1)

    def mapping(self, indent):
        result = {}
        while True:
            head = self.peek()
            if head is None or head[0] < indent:
                return result
            ind, content = head
            split = _yaml_split_key(content) if ind == indent else None
            if split is None:
                if ind == indent and (content == "-" or content.startswith("- ")):
                    return result
                raise YamlError("Bad indentation on line %d" % (self.index + 1))
            key, rest = split
            self.index += 1
            result[key] = self.value(rest, indent, in_mapping=True)

    def sequence(self, indent):
        result = []
        while True:
            head = self.peek()
            if head is None or head[0] < indent:
                return result
            ind, content = head
            if ind > indent or not (content == "-" or content.startswith("- ")):
                if ind == indent:
                    return result
                raise YamlError("Bad indentation on line %d" % (self.index + 1))
            rest = content[1:].lstrip(" ")
            if rest and (rest == "-" or rest.startswith("- ") or _yaml_split_key(rest) is not None):
                item_indent = indent + len(content) - len(rest)
                self.lines[self.index] = " " * item_indent + rest
                result.append(self.block(item_indent))
            else:
                self.index += 1
                result.append(self.value(rest, indent))

    def value(self, rest, indent, in_mapping=False):
        if rest == "":
            head = self.peek()
            if head is None:
                return None
            ind, content = head
            if ind > indent:
                return self.block(ind)
            if in_mapping and ind == indent and (content == "-" or content.startswith("- ")):
                return self.sequence(ind)
            return None
        return self.scalar(rest, indent)

    def scalar(self, rest, indent):
        if _YAML_BLOCK_SCALAR.fullmatch(rest):
            return self.block_scalar(rest, indent)
        if rest[0] in "[{":
            # Flow collections may span several lines.
            text = rest
            while _yaml_flow_balance(text) > 0 and self.index < len(self.lines):
                text += " " + _yaml_strip_comment(self.lines[self.index]).strip()
                self.index += 1
            return _yaml_inline(text)
        if rest[0] in "\"'":
            # Quoted scalars may span several lines.
            text = rest
            while True:
                try:
                    return _yaml_inline(text)
                except YamlError:
                    if self.index >= len(self.lines):
                        raise
                    text += " " + self.lines[self.index].strip()
                    self.index += 1
        # Plain scalars may continue on more-indented lines.
        parts = [rest]
        while True:
            head = self.peek()
            if head is None or head[0] <= indent:
                break
            if _yaml_split_key(head[1]) is not None or head[1].startswith("- "):
                break
            parts.append(head[1])
            self.index += 1
        return _yaml_inline(" ".join(parts))

    def block_scalar(self, header, indent):
        chomp = "+" if "+" in header else "-" if "-" in header else ""
        lines = []
        block_indent = None
        while self.index < len(self.lines):
            raw = self.lines[self.index].rstrip()
            if raw.strip():
                current = len(raw) - len(raw.lstrip(" "))
                if current <= indent:
                    break
                if block_indent is None:
                    block_indent = current
                if current < block_indent:
                    break
                lines.append(raw[block_indent:])
            else:
                lines.append("")
            self.index += 1
        trailing = 0
        while lines and lines[-1] == "":
            lines.pop()
            trailing += 1
        if header[0] == ">":
            folded = []
            for line in lines:
                if folded and folded[-1] != "" and line != "" and not line.startswith(" "):
                    folded[-1] += " " + line
                else:
                    folded.append(line)
            text = "\n".join(folded)
        else:
            text = "\n".join(lines)
        if chomp == "-" or not lines:
            return text
        if chomp == "+":
            return text + "\n" * (trailing + 1)
        return text + "\n"


def yaml_load(text):
    """Parse a YAML document (block/flow collections and scalars)."""
    return _YamlParser(text).parse()


def _yaml_scalar(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if (text == "" or text != text.strip() or ": " in text or " #" in text
            or text[0] in "[]{},&*!|>'\"%`#?" or text == "-" or text.startswith("- ") or "\n" in text
            or not isinstance(_yaml_resolve(text), str)):
        return json.dumps(text)
    return text


def yaml_dump_lines(value, indent=0):
    pad = " " * indent
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append("%s%s:" % (pad, _yaml_scalar(key)))
                lines.extend(yaml_dump_lines(item, indent + 2))
            else:
                lines.append("%s%s: %s" % (pad, _yaml_scalar(key), _yaml_inline_dump(item)))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)) and item:
                nested = yaml_dump_lines(item, indent + 2)
                lines.append("%s- %s" % (pad, nested[0].lstrip()))
                lines.extend(nested[1:])
            else:
                lines.append("%s- %s" % (pad, _yaml_inline_dump(item)))
    else:
        lines.append(pad + _yaml_scalar(value))
    return lines


def _yaml_inline_dump(value):
    if isinstance(value, dict):
        return "{}"
    if isinstance(value, list):
        return "[]"
    return _yaml_scalar(value)


# ---------------------------------------------------------------------------
# Synopsis parsing
# ---------------------------------------------------------------------------

_P_NAME = r"[a-z\-_0-9]+"
_P_VALUE = r"[a-zA-Z\-_|,0-9]+"


def _strip_optional(token):
    if len(token) >= 2 and token.startswith("[") and token.endswith("]"):
        return True, token[1:-1]
    return False, token


def _strip_repeating(token):
    if token.endswith("..."):
        return True, token[:-3]
    return False, token


def classify_token(token):
    """Classify a single synopsis token into a parameter spec dict."""
    param = {"token": token}
    param["optional"], body = _strip_optional(token)
    param["repeating"], body = _strip_repeating(body)

    if body == "--<field>=<value>":
        param["type"] = "generic"
        return param

    match = re.fullmatch(r"<(%s)>" % _P_VALUE, body)
    if match:
        param["type"] = "positional"
        param["name"] = match.group(1)
        return param

    match = re.match(r"--(\[no-\])?(%s)" % _P_NAME, body)
    if match:
        param["name"] = match.group(2)
        param["negatable"] = bool(match.group(1))
        rest = body[match.end():]
        if rest == "":
            param["type"] = "flag"
            return param
        value_optional, rest = _strip_optional(rest)
        value_match = re.fullmatch(r"=<(%s)>" % _P_VALUE, rest)
        if value_match:
            param["type"] = "assoc"
            param["value"] = {"optional": value_optional, "name": value_match.group(1)}
            return param

    return {"token": token, "type": "unknown", "optional": False, "repeating": False}


def parse_synopsis(synopsis, strict=False):
    """Parse a synopsis string into a list of parameter specs.

    With ``strict=True`` a malformed token raises :class:`SynopsisError`.
    """
    params = []
    for token in (synopsis or "").split():
        param = classify_token(token)
        if strict and param["type"] == "unknown":
            raise SynopsisError("Invalid synopsis token: '%s'" % token)
        params.append(param)
    return params


# ---------------------------------------------------------------------------
# Command tree
# ---------------------------------------------------------------------------

class Command:
    def __init__(self, name, parent=None, description="", synopsis="", alias=None,
                 handler=None, defaults=None, longdesc="", stdin_args=()):
        self.name = name
        self.parent = parent
        self.description = description
        self.synopsis = " ".join((synopsis or "").split())
        self.alias = alias
        self.handler = handler
        self.defaults = dict(defaults or {})
        self.longdesc = longdesc
        # Positional value arguments that may be read from STDIN (JSON-decoded
        # when --format=json is active).
        self.stdin_args = set(stdin_args)
        self.subcommands = {}
        self.params = parse_synopsis(self.synopsis, strict=True)

    # -- tree helpers ------------------------------------------------------
    @property
    def path(self):
        parts = []
        node = self
        while node is not None and node.parent is not None:
            parts.append(node.name)
            node = node.parent
        return " ".join(reversed(parts))

    def add_subcommand(self, command):
        command.parent = self
        self.subcommands[command.name] = command

    def sorted_subcommands(self):
        return [self.subcommands[k] for k in sorted(self.subcommands, key=sort_key)]

    def enabled_subcommands(self):
        return [sub for sub in self.sorted_subcommands() if not is_command_disabled(sub)]

    def find_subcommand(self, name):
        if name in self.subcommands:
            return self.subcommands[name]
        for sub in self.sorted_subcommands():
            if sub.alias and sub.alias == name:
                return sub
        return None

    def can_have_subcommands(self):
        return bool(self.subcommands)

    # -- usage helpers -----------------------------------------------------
    def usage_line(self):
        line = "%s %s" % (PROG, self.path) if self.path else PROG
        if self.subcommands and self.handler is None:
            return line + " <command>"
        if self.synopsis:
            line += " " + self.synopsis
        return line

    def show_usage(self):
        if self.subcommands and self.handler is None:
            lines = [sub.usage_line() for sub in self.enabled_subcommands()]
            for i, line in enumerate(lines):
                out(("usage: " if i == 0 else "   or: ") + line)
            out()
            out("See '%s help %s <command>' for more information on a specific command."
                % (PROG, self.path))
        else:
            out("usage: " + self.usage_line())

    def known_assoc(self):
        return [p["name"] for p in self.params if p["type"] in ("assoc", "flag")]


ROOT = Command("", description="Manage applications from the command line.")


def register(path, description="", synopsis="", alias=None, handler=None,
             defaults=None, longdesc="", stdin_args=()):
    """Register a command (and any missing parent namespaces)."""
    parse_synopsis(synopsis, strict=True)
    parts = path.split()
    node = ROOT
    for part in parts[:-1]:
        child = node.subcommands.get(part)
        if child is None:
            child = Command(part)
            node.add_subcommand(child)
        node = child
    existing = node.subcommands.get(parts[-1])
    command = Command(parts[-1], description=description, synopsis=synopsis,
                      alias=alias, handler=handler, defaults=defaults, longdesc=longdesc,
                      stdin_args=stdin_args)
    if existing is not None:
        for sub in existing.subcommands.values():
            command.add_subcommand(sub)
    node.add_subcommand(command)
    return command


def iter_commands(node=None):
    node = node or ROOT
    for sub in node.sorted_subcommands():
        yield sub
        yield from iter_commands(sub)


def unknown_command_error(name, parent):
    if parent is ROOT:
        message = ("'%s' is not a registered %s command. See '%s help' for available commands."
                   % (name, PROG, PROG))
    else:
        message = ("'%s' is not a registered subcommand of '%s'. See '%s help %s' for "
                   "available subcommands." % (name, parent.path, PROG, parent.path))
    suggestion = get_suggestion(name, parent.subcommands.keys())
    if suggestion:
        message += "\nDid you mean '%s'?" % suggestion
    error(message)


def resolve_command(positionals):
    """Walk the tree. Returns (command, remaining_positionals)."""
    node = ROOT
    remaining = list(positionals)
    typed = []
    while remaining and node.can_have_subcommands():
        token = remaining[0]
        child = node.find_subcommand(token)
        if child is None:
            if node.handler is not None:
                break
            unknown_command_error(token, node)
        typed.append(token)
        if is_command_disabled(child):
            error("The '%s' command has been disabled." % " ".join(typed))
        node = child
        remaining.pop(0)
    return node, remaining


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _param(runtime=None, file=False, default=None, multiple=False, deprecated=False,
           hidden=False):
    """Describe a global parameter.

    ``runtime`` is the synopsis token when the parameter may be passed as a
    ``--flag`` (None otherwise); ``file`` tells whether config files may set it.
    """
    return {"runtime": runtime, "file": file, "default": default, "multiple": multiple,
            "deprecated": deprecated, "hidden": hidden}


GLOBAL_SPEC = {
    "path": _param("[--path=<path>]", file=True),
    "url": _param("[--url=<url>]", file=True),
    "user": _param("[--user=<id|login|email>]", file=True),
    "ssh": _param("[--ssh=<host>]", file=True),
    "skip-plugins": _param("[--skip-plugins[=<plugins>]]", file=True),
    "skip-themes": _param("[--skip-themes[=<themes>]]", file=True),
    "skip-packages": _param("[--skip-packages]", file=True),
    "require": _param("[--require=<path>]", file=True, multiple=True),
    "exec": _param("[--exec=<php-code>]"),
    "context": _param("[--context=<context>]", file=True),
    "prompt": _param("[--prompt[=<assoc>]]"),
    "blog": _param("[--blog=<url>]", deprecated=True, hidden=True),
    "disabled_commands": _param(file=True, default=[], multiple=True),
    "projects_path": _param(file=True),
    "locale": _param(file=True, default="en_US"),
    "cert-email": _param(file=True),
    "env": _param(file=True),
    "admin-email": _param(file=True),
    "sysctl": _param(file=True),
    "skip-tty": _param(file=True, default=False),
    "custom-compose": _param(file=True),
    "installer_version": _param(file=True, default="stable"),
    "color": _param("[--[no-]color]", file=True, default="auto"),
    "debug": _param("[--debug[=<group>]]", default=False),
    "quiet": _param("[--quiet]", default=False),
}
GLOBAL_PARAMS = parse_synopsis(
    " ".join(spec["runtime"] for spec in GLOBAL_SPEC.values() if spec["runtime"]), strict=True)
GLOBAL_NAMES = {p["name"] for p in GLOBAL_PARAMS}


def parse_token(token):
    """Return (key, value) for an option token, or None for a positional."""
    if not token.startswith("--") or token == "--":
        return None
    body = token[2:]
    if "=" in body:
        key, value = body.split("=", 1)
        return key, value
    if body.startswith("no-") and len(body) > 3:
        return body[3:], False
    return body, True


def split_args(tokens, strict):
    """Split raw tokens into positionals, command assoc args and global config."""
    positionals = []
    assoc = []
    runtime = {}
    seen_positional = False
    positional_only = False
    for token in tokens:
        if positional_only:
            positionals.append(token)
            seen_positional = True
            continue
        if token == "--":
            positional_only = True
            continue
        parsed = parse_token(token)
        if parsed is None:
            positionals.append(token)
            seen_positional = True
            continue
        key, value = parsed
        is_global = key in GLOBAL_NAMES and not (strict and seen_positional)
        if is_global:
            runtime[key] = value
        else:
            assoc.append((key, value))
    return positionals, assoc, runtime


def rewrite_args(tokens):
    """Apply the --help and --version rewrites."""
    head = tokens
    tail = []
    if "--" in tokens:
        idx = tokens.index("--")
        head, tail = tokens[:idx], tokens[idx:]

    if "--help" in head:
        kept = [t for t in head if t != "--help"]
        new = ["help"]
        for token in kept + tail:
            parsed = parse_token(token)
            if parsed is None or token == "--":
                if token != "--":
                    new.append(token)
            elif parsed[0] in GLOBAL_NAMES:
                new.append(token)
        return new

    if "--version" in head and not tail:
        rest = [t for t in head if t != "--version"]
        if all(parse_token(t) is not None for t in rest):
            return ["cli", "version"] + rest
    return tokens


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def fill_from_stdin(command, args, positional_specs, assoc_list):
    if len(args) >= len(positional_specs):
        return args
    spec = positional_specs[len(args)]
    is_value = spec["name"] in command.stdin_args
    if spec["optional"] and not is_value:
        return args
    raw = read_stdin()
    if raw is None:
        return args
    fmt = command.defaults.get("format")
    for key, value in assoc_list:
        if key == "format":
            fmt = value
    if is_value and fmt == "json":
        try:
            args.append(json.loads(raw))
        except ValueError:
            error("Invalid JSON: %s" % raw, sensitive=True, box=False)
    elif spec["repeating"]:
        args.extend(raw.split())
    else:
        args.append(raw)
    return args


def validate_and_prepare(command, args, assoc_list):
    params = command.params
    positional_specs = [p for p in params if p["type"] == "positional"]
    assoc_specs = [p for p in params if p["type"] in ("assoc", "flag")]
    has_generic = any(p["type"] == "generic" for p in params)

    # 0. A missing positional may be supplied through STDIN.
    args = fill_from_stdin(command, list(args), positional_specs, assoc_list)

    # 1. Required positionals.
    required = 0
    for spec in positional_specs:
        if not spec["optional"]:
            required += 1
    if len(args) < required:
        command.show_usage()
        raise AppctlExit(1)

    # 2. Excess positionals.
    if not any(p["repeating"] for p in positional_specs):
        if len(args) > len(positional_specs):
            extra = args[len(positional_specs):]
            error("Too many positional arguments: " + " ".join(extra))

    assoc = {}
    for key, value in assoc_list:
        assoc[key] = value

    # 3/4. Associative arguments.
    errors = []
    known = [p["name"] for p in assoc_specs]
    for spec in assoc_specs:
        key = spec["name"]
        if spec["type"] == "assoc":
            present = key in assoc
            value = assoc.get(key)
            if not spec["optional"]:
                if not present or value is True or value is False or value == "":
                    errors.append("missing --%s parameter" % key)
                    continue
            elif present and (value is True or value is False) and not spec["value"]["optional"]:
                warning("--%s parameter needs a value" % key)
                del assoc[key]
        else:
            if not spec["optional"] and key not in assoc:
                errors.append("missing --%s parameter" % key)

    if not has_generic:
        seen = set()
        for key, _ in assoc_list:
            if key in known or key in seen:
                continue
            seen.add(key)
            message = "unknown --%s parameter" % key
            suggestion = get_suggestion(key, known, synonyms=False)
            if suggestion:
                message += "\nDid you mean '--%s'?" % suggestion
            errors.append(message)

    if errors:
        error("Parameter errors:\n" + "\n".join(errors))

    # Apply defaults.
    args = list(args)
    for index, spec in enumerate(positional_specs):
        if index >= len(args) and spec["name"] in command.defaults and not spec["repeating"]:
            args.append(command.defaults[spec["name"]])
    for spec in assoc_specs:
        if spec["name"] not in assoc and spec["name"] in command.defaults:
            assoc[spec["name"]] = command.defaults[spec["name"]]
    return args, assoc


# ---------------------------------------------------------------------------
# Output formatting helpers for handlers
# ---------------------------------------------------------------------------

FORMATS = ("table", "csv", "json", "yaml", "count", "ids")


def cell_value(value):
    """Render a value for table/CSV output; complex values become JSON strings."""
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value)
    return str(value)


def dump_json(value):
    return json.dumps(value, indent=4)


def ascii_table(headers, rows):
    """Fixed-width table; each column is as wide as its widest value."""
    widths = [max([len(h)] + [len(row[i]) for row in rows]) for i, h in enumerate(headers)]
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    lines = [sep, "| " + " | ".join(h.ljust(w) for h, w in zip(headers, widths)) + " |", sep]
    for row in rows:
        lines.append("| " + " | ".join(c.ljust(w) for c, w in zip(row, widths)) + " |")
    lines.append(sep)
    return lines


class Formatter:
    """Render command results according to --format, --fields and --field."""

    def __init__(self, assoc, fields, prefix=None):
        self.format = assoc.get("format") if isinstance(assoc.get("format"), str) else None
        self.format = self.format or "table"
        field = assoc.get("field")
        self.field = field if isinstance(field, str) and field != "" else None
        fields_arg = assoc.get("fields")
        self.requested = None
        if isinstance(fields_arg, str) and fields_arg.strip():
            self.requested = [f.strip() for f in fields_arg.split(",") if f.strip()]
        self.default_fields = list(fields)
        self.prefix = prefix

    def find_key(self, item, field):
        """Return the item key matching ``field`` (prefix-aware, case-insensitive)."""
        candidates = [field]
        if self.prefix:
            candidates.append("%s_%s" % (self.prefix, field))
        for candidate in candidates:
            if candidate in item:
                return candidate
        for candidate in candidates:
            for key in item:
                if key.lower() == candidate.lower():
                    return key
        error("Invalid field: %s." % field)

    def reference(self, items):
        return items[0] if items else dict.fromkeys(self.default_fields)

    def columns(self, items):
        if self.requested is None:
            return list(self.default_fields)
        reference = self.reference(items)
        return [self.find_key(reference, f) for f in self.requested]

    def check_format(self):
        if self.format not in FORMATS:
            error("Invalid format: %s" % self.format)

    def id_key(self, item, columns):
        for key in item:
            if key.lower() == "id":
                return key
        if self.prefix:
            for key in item:
                if key.lower() == "%s_id" % self.prefix.lower():
                    return key
        return columns[0] if columns else None

    def display_field(self, items, single):
        values = []
        for item in items:
            key = self.find_key(item, self.field)
            values.append(item.get(key))
        if not items:
            self.find_key(self.reference(items), self.field)
        if self.format == "json":
            out(dump_json(values[0] if single else values))
            return
        for value in values:
            out(cell_value(value))

    def display_items(self, items, single=False):
        items = list(items)
        if self.field:
            self.display_field(items, single)
            return
        self.check_format()
        columns = self.columns(items)
        rows = [{c: item.get(c) for c in columns} for item in items]
        fmt = self.format
        if fmt == "count":
            out(str(len(items)))
        elif fmt == "ids":
            ids = []
            for item in items:
                key = self.id_key(item, columns)
                ids.append(cell_value(item.get(key)) if key else "")
            out(" ".join(ids))
        elif fmt == "json":
            out(dump_json(rows[0] if single and rows else rows))
        elif fmt == "yaml":
            data = rows[0] if single and rows else rows
            out("---")
            lines = yaml_dump_lines(data) if data else [_yaml_inline_dump(data)]
            for line in lines:
                out(line)
        elif fmt == "csv":
            buffer = io.StringIO()
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(columns)
            for row in rows:
                writer.writerow([cell_value(row[c]) for c in columns])
            sys.stdout.write(buffer.getvalue())
        elif len(rows) == 1:
            table_rows = [[c, cell_value(rows[0][c])] for c in columns]
            for line in ascii_table(["Field", "Value"], table_rows):
                out(line)
        else:
            table_rows = [[cell_value(row[c]) for c in columns] for row in rows]
            for line in ascii_table(columns, table_rows):
                out(line)

    def display_item(self, item):
        self.display_items([item], single=True)


def render_items(assoc, items, default_fields, prefix=None):
    Formatter(assoc, default_fields, prefix).display_items(items)


def render_item(assoc, item, default_fields=None, prefix=None):
    fields = default_fields if default_fields is not None else list(item.keys())
    Formatter(assoc, fields, prefix).display_item(item)


def render_value(value, fmt):
    if fmt == "json":
        out(dump_json(value))
    elif isinstance(value, (dict, list)):
        out(json.dumps(value))
    else:
        out(str(value))


def describe(**kwargs):
    return ", ".join("%s: %s" % (k, v) for k, v in kwargs.items())


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

def column_listing(commands):
    if not commands:
        return []
    width = max(len(c.name) for c in commands)
    return ["  %s  %s" % (c.name.ljust(width), c.description) for c in commands]


def show_root_help():
    out("usage: %s <command> [<subcommand>] [<args>] [--<flags>]" % PROG)
    out()
    out(ROOT.description)
    out()
    out("Available commands:")
    out()
    for line in column_listing(ROOT.enabled_subcommands()):
        out(line)
    out()
    out("See '%s help <command>' for more information on a specific command." % PROG)


def show_command_help(command):
    out("NAME")
    out()
    out("  %s %s" % (PROG, command.path))
    out()
    if command.description:
        out("DESCRIPTION")
        out()
        out("  " + command.description)
        out()
    out("SYNOPSIS")
    out()
    out("  " + command.usage_line())
    out()
    if command.alias:
        out("ALIAS")
        out()
        out("  " + command.alias)
        out()
    if command.handler is not None and command.params:
        out("OPTIONS")
        out()
        for spec in command.params:
            out("  " + spec["token"])
            name = spec.get("name")
            if name and name in command.defaults:
                out("    default: %s" % format_default(command.defaults[name]))
        out()
    if command.longdesc:
        out(command.longdesc.rstrip())
        out()
    if command.subcommands:
        out("SUBCOMMANDS")
        out()
        for line in column_listing(command.enabled_subcommands()):
            out(line)
        out()
        out("See '%s help %s <command>' for more information on a specific command."
            % (PROG, command.path))


def format_default(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def cmd_help(args, assoc):
    if not args:
        show_root_help()
        return
    command, remaining = resolve_command(args)
    if remaining:
        unknown_command_error(remaining[0], command)
    show_command_help(command)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_cli_version(args, assoc):
    out("%s %s" % (PROG, VERSION))


def cmd_cli_info(args, assoc):
    info = {
        "os": sys.platform,
        "python_binary": sys.executable,
        "python_version": sys.version.split()[0],
        "appctl_version": VERSION,
        "strict_args_mode": bool(os.environ.get(STRICT_ENV)),
        "global_config": Runtime.global_config_path or global_config_path(),
        "project_config": Runtime.project_config_path or "",
        "packages_dir": packages_dir(),
    }
    if assoc.get("format") == "json":
        out(dump_json(info))
    else:
        width = max(len(k) for k in info)
        for key, value in info.items():
            out("%s  %s" % (key.ljust(width), format_default(value)))


def completion_candidates(words, current):
    node = ROOT
    used = set()
    for word in words:
        parsed = parse_token(word)
        if parsed is not None:
            used.add(parsed[0])
            continue
        child = node.find_subcommand(word) if node.can_have_subcommands() else None
        if child is not None and not is_command_disabled(child):
            node = child
    if node.can_have_subcommands() and not current.startswith("-"):
        names = [sub.name for sub in node.enabled_subcommands()]
    else:
        params = list(node.params) + list(GLOBAL_PARAMS) if node.handler else []
        names = []
        for spec in params:
            if spec["type"] not in ("assoc", "flag") or spec["name"] in used:
                continue
            names.append("--%s%s" % (spec["name"], "=" if spec["type"] == "assoc" else ""))
    seen = []
    for name in names:
        if name.startswith(current) and name not in seen:
            seen.append(name)
    return seen


def cmd_cli_completions(args, assoc):
    line = assoc.get("line") if isinstance(assoc.get("line"), str) else ""
    point = assoc.get("point")
    if isinstance(point, str) and point.isdigit():
        line = line[:int(point)]
    words = line.split()
    if words:
        words = words[1:]
    current = ""
    if words and not line[-1:].isspace():
        current = words.pop()
    for name in completion_candidates(words, current):
        out(name)


def cmd_cli_has_command(args, assoc):
    node = ROOT
    for part in args[0].split():
        node = node.find_subcommand(part) if node else None
        if node is None or is_command_disabled(node):
            raise AppctlExit(1)
    raise AppctlExit(0)


def _dump(command):
    data = {
        "name": command.name,
        "description": command.description,
        "synopsis": command.synopsis,
        "alias": command.alias,
        "subcommands": [_dump(s) for s in command.sorted_subcommands()],
    }
    return data


def cmd_cli_cmd_dump(args, assoc):
    data = _dump(ROOT)
    data["name"] = PROG
    out(json.dumps(data))


def cmd_cli_check_update(args, assoc):
    success("appctl is at the latest version.")


def cmd_cli_alias_list(args, assoc):
    aliases = Runtime.aliases
    if not aliases or assoc.get("format") == "json":
        render_value(aliases, assoc.get("format"))
        return
    out("---")
    for line in yaml_dump_lines(aliases):
        out(line)


def cmd_cli_alias_add(args, assoc):
    success("Added '%s' alias." % args[0])


def cmd_cli_alias_delete(args, assoc):
    success("Deleted '%s' alias." % args[0])


SAMPLE_SITES = [
    {"name": "main", "url": "https://example.com", "type": "standard", "status": "active"},
    {"name": "blog", "url": "https://blog.example.com", "type": "blog", "status": "active"},
]


def cmd_site_create(args, assoc):
    name = args[0]
    title = assoc.get("title") or name
    if assoc.get("porcelain"):
        out(name)
        return
    success("Created site '%s' (%s)." % (name, describe(type=assoc.get("type"), title=title)))


def cmd_site_delete(args, assoc):
    if not confirm("Are you sure you want to delete the '%s' site?" % args[0], assoc):
        return
    success("Deleted site '%s'." % args[0])


def cmd_site_list(args, assoc):
    render_items(assoc, SAMPLE_SITES, ["name", "url", "type", "status"])


def cmd_site_update(args, assoc):
    fields = {k: v for k, v in assoc.items()}
    if not fields:
        error("Need some fields to update.")
    success("Updated site '%s' (%s)." % (args[0], describe(**fields)))


def cmd_site_activate(args, assoc):
    for name in args:
        success("Site '%s' activated." % name)


def cmd_site_deactivate(args, assoc):
    for name in args:
        success("Site '%s' deactivated." % name)


def cmd_site_empty(args, assoc):
    url = Runtime.config.get("url") or "default"
    if not confirm("Are you sure you want to empty the site at '%s' of all posts, links, "
                   "comments, and terms?" % url, assoc):
        return
    success("The site at '%s' was emptied." % url)


def cmd_site_meta_get(args, assoc):
    render_value("", assoc.get("format"))


def cmd_site_meta_set(args, assoc):
    success("Updated meta '%s' of site '%s' to '%s'." % (args[1], args[0], args[2]))


def cmd_site_meta_delete(args, assoc):
    success("Deleted meta '%s' of site '%s'." % (args[1], args[0]))


def cmd_site_meta_list(args, assoc):
    render_items(assoc, [], ["site", "meta_key", "meta_value"])


CONFIG = {"DB_NAME": "app", "DB_USER": "root", "DB_HOST": "localhost", "DEBUG": "false"}


def cmd_config_get(args, assoc):
    if args[0] not in CONFIG:
        error("The constant or variable '%s' is not defined in the config file." % args[0])
    render_value(CONFIG[args[0]], assoc.get("format"))


def cmd_config_set(args, assoc):
    success("Updated the constant '%s' in the config file with the value '%s' (%s)."
            % (args[0], args[1], describe(type=assoc.get("type"))))


def cmd_config_delete(args, assoc):
    if args[0] not in CONFIG:
        error("The constant or variable '%s' is not defined in the config file." % args[0])
    success("Deleted the constant '%s' from the config file." % args[0])


def cmd_config_list(args, assoc):
    items = [{"name": k, "value": v, "type": "constant"} for k, v in CONFIG.items()
             if not args or any(f in k for f in args)]
    render_items(assoc, items, ["name", "value", "type"])


def cmd_config_path(args, assoc):
    out(os.path.join(Runtime.config.get("path") or os.getcwd(), "app-config.php"))


def cmd_config_create(args, assoc):
    success("Generated config file (%s)." % describe(
        dbname=assoc["dbname"], dbuser=assoc["dbuser"], dbhost=assoc.get("dbhost"),
        dbprefix=assoc.get("dbprefix")))


def cmd_cache_flush(args, assoc):
    success("The cache was flushed.")


def cmd_cache_get(args, assoc):
    error("Object with key '%s' and group '%s' not found." % (args[0], args[1]))


def cmd_cache_set(args, assoc):
    success("Set object '%s' in group '%s' (%s)." % (args[0], args[2], describe(expiration=args[3])))


def cmd_cache_delete(args, assoc):
    success("Object deleted.")


def cmd_db_create(args, assoc):
    success("Database created.")


def cmd_db_drop(args, assoc):
    if not confirm("Are you sure you want to drop the '%s' database?" % CONFIG["DB_NAME"], assoc):
        return
    success("Database dropped.")


def cmd_db_reset(args, assoc):
    if not confirm("Are you sure you want to reset the '%s' database?" % CONFIG["DB_NAME"], assoc):
        return
    success("Database reset.")


def cmd_db_export(args, assoc):
    name = args[0] if args else "database.sql"
    if assoc.get("porcelain"):
        out(name)
    else:
        success("Exported to '%s'." % name)


def cmd_db_import(args, assoc):
    success("Imported from '%s'." % args[0])


def cmd_db_query(args, assoc):
    out(args[0] if args else "")


def cmd_db_size(args, assoc):
    render_items(assoc, [{"Name": "app", "Size": "0 B"}], ["Name", "Size"])


OPTIONS = {"siteurl": "https://example.com", "blogname": "Example", "admin_email": "admin@example.com"}


def cmd_option_get(args, assoc):
    if args[0] not in OPTIONS:
        error("Could not get '%s' option. Does it exist?" % args[0])
    render_value(OPTIONS[args[0]], assoc.get("format"))


def cmd_option_add(args, assoc):
    success("Added '%s' option (%s)." % (args[0], describe(autoload=assoc.get("autoload"))))


def cmd_option_update(args, assoc):
    success("Updated '%s' option (%s)." % (args[0], describe(autoload=assoc.get("autoload"))))


def cmd_option_delete(args, assoc):
    for key in args:
        success("Deleted '%s' option." % key)


def cmd_option_list(args, assoc):
    import fnmatch
    pattern = assoc.get("search")
    items = [{"option_name": k, "option_value": v} for k, v in OPTIONS.items()
             if not pattern or fnmatch.fnmatch(k, pattern)]
    render_items(assoc, items, ["option_name", "option_value"], prefix="option")


SAMPLE_PLUGINS = [
    {"name": "akismet", "status": "active", "update": "none", "version": "5.3"},
    {"name": "hello", "status": "inactive", "update": "none", "version": "1.7.2"},
]


def _plugin_targets(args, assoc, verb):
    if assoc.get("all"):
        return [p["name"] for p in SAMPLE_PLUGINS]
    if not args:
        error("Please specify one or more plugins, or use --all.")
    return args


def cmd_plugin_install(args, assoc):
    for name in args:
        log("Installing %s%s" % (name, " (%s)" % assoc["version"] if assoc.get("version") else ""))
        if assoc.get("activate"):
            log("Activating '%s'..." % name)
    success("Installed %d of %d plugins." % (len(args), len(args)))


def cmd_plugin_activate(args, assoc):
    targets = _plugin_targets(args, assoc, "activate")
    for name in targets:
        log("Plugin '%s' activated." % name)
    success("Activated %d of %d plugins." % (len(targets), len(targets)))


def cmd_plugin_deactivate(args, assoc):
    targets = _plugin_targets(args, assoc, "deactivate")
    for name in targets:
        log("Plugin '%s' deactivated." % name)
    success("Deactivated %d of %d plugins." % (len(targets), len(targets)))


def cmd_plugin_delete(args, assoc):
    targets = _plugin_targets(args, assoc, "delete")
    success("Deleted %d of %d plugins." % (len(targets), len(targets)))


def cmd_plugin_uninstall(args, assoc):
    targets = _plugin_targets(args, assoc, "uninstall")
    success("Uninstalled %d of %d plugins." % (len(targets), len(targets)))


def cmd_plugin_update(args, assoc):
    targets = _plugin_targets(args, assoc, "update")
    if assoc.get("dry-run"):
        log("Available plugin updates: none")
        return
    success("Plugins already updated: %d." % len(targets))


def cmd_plugin_list(args, assoc):
    items = SAMPLE_PLUGINS
    if isinstance(assoc.get("status"), str):
        items = [p for p in items if p["status"] == assoc["status"]]
    render_items(assoc, items, ["name", "status", "update", "version"])


def cmd_plugin_status(args, assoc):
    if args:
        for p in SAMPLE_PLUGINS:
            if p["name"] == args[0]:
                out("Plugin %s details:" % p["name"])
                out("    Status: %s" % p["status"].capitalize())
                out("    Version: %s" % p["version"])
                return
        error("The '%s' plugin could not be found." % args[0])
    out("%d installed plugins:" % len(SAMPLE_PLUGINS))
    for p in SAMPLE_PLUGINS:
        out("  %s %s %s" % ("A" if p["status"] == "active" else "I", p["name"], p["version"]))


SAMPLE_THEMES = [
    {"name": "default", "status": "active", "update": "none", "version": "1.0"},
    {"name": "classic", "status": "inactive", "update": "none", "version": "2.1"},
]


def cmd_theme_activate(args, assoc):
    success("Switched to '%s' theme." % args[0])


def cmd_theme_install(args, assoc):
    for name in args:
        log("Installing %s" % name)
    success("Installed %d of %d themes." % (len(args), len(args)))


def cmd_theme_delete(args, assoc):
    names = [t["name"] for t in SAMPLE_THEMES] if assoc.get("all") else args
    if not names:
        error("Please specify one or more themes, or use --all.")
    success("Deleted %d of %d themes." % (len(names), len(names)))


def cmd_theme_list(args, assoc):
    render_items(assoc, SAMPLE_THEMES, ["name", "status", "update", "version"])


SAMPLE_POSTS = [
    {"ID": 1, "post_title": "Hello world!", "post_type": "post", "post_status": "publish"},
    {"ID": 2, "post_title": "Sample Page", "post_type": "page", "post_status": "publish"},
]


def cmd_post_create(args, assoc):
    if assoc.get("porcelain"):
        out("3")
        return
    fields = {k: v for k, v in assoc.items() if k != "porcelain"}
    success("Created post 3 (%s)." % describe(**fields))


def cmd_post_get(args, assoc):
    for post in SAMPLE_POSTS:
        if str(post["ID"]) == str(args[0]):
            render_item(assoc, post, prefix="post")
            return
    error("Could not find the post with ID %s." % args[0])


def cmd_post_list(args, assoc):
    items = SAMPLE_POSTS
    filters = {k: v for k, v in assoc.items() if k not in ("format", "field", "fields")}
    for key, value in filters.items():
        items = [p for p in items if str(p.get(key)) == str(value)]
    render_items(assoc, items, ["ID", "post_title", "post_type", "post_status"], prefix="post")


def cmd_post_update(args, assoc):
    fields = {k: v for k, v in assoc.items()}
    if not fields:
        error("Need some fields to update.")
    for post_id in args:
        success("Updated post %s." % post_id)


def cmd_post_delete(args, assoc):
    for post_id in args:
        if assoc.get("force"):
            success("Deleted post %s." % post_id)
        else:
            success("Trashed post %s." % post_id)


SAMPLE_USERS = [
    {"ID": 1, "user_login": "admin", "user_email": "admin@example.com", "roles": "administrator"},
]


def cmd_user_create(args, assoc):
    if assoc.get("porcelain"):
        out("2")
        return
    success("Created user 2 (%s)." % describe(login=args[0], email=args[1], role=assoc.get("role")))
    if not assoc.get("user_pass"):
        import secrets
        log("Password: %s" % secrets.token_urlsafe(18), sensitive=True)


def cmd_user_delete(args, assoc):
    if not assoc.get("reassign") and not confirm(
            "--reassign parameter not passed. All associated posts will be deleted. Proceed?",
            assoc):
        return
    for user in args:
        success("Removed user %s%s." % (user, " (reassigned to %s)" % assoc["reassign"]
                                         if assoc.get("reassign") else ""))


def cmd_user_get(args, assoc):
    for user in SAMPLE_USERS:
        if str(args[0]) in (str(user["ID"]), user["user_login"], user["user_email"]):
            render_item(assoc, user, prefix="user")
            return
    error("Invalid user ID, email or login: '%s'" % args[0])


def cmd_user_list(args, assoc):
    items = SAMPLE_USERS
    if isinstance(assoc.get("role"), str):
        items = [u for u in items if u["roles"] == assoc["role"]]
    render_items(assoc, items, ["ID", "user_login", "user_email", "roles"], prefix="user")


def cmd_user_update(args, assoc):
    fields = {k: v for k, v in assoc.items() if k != "skip-email"}
    if not fields:
        error("Need some fields to update.")
    for user in args:
        success("Updated user %s." % user)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def build_registry():
    register("help", "Get help on appctl, or on a specific command.",
             "[<command>...]", handler=cmd_help)

    register("cli", "Review current appctl info, check for updates, or see defined aliases.")
    register("cli version", "Print appctl version.", "", handler=cmd_cli_version)
    register("cli info", "Print various details about the appctl environment.",
             "[--format=<format>]", handler=cmd_cli_info, defaults={"format": "list"})
    register("cli check-update", "Check to see if there is a newer version of appctl available.",
             "[--patch] [--minor] [--major] [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_cli_check_update, defaults={"format": "table"})
    register("cli has-command", "Detect if a command exists.", "<command_name>",
             handler=cmd_cli_has_command)
    register("cli completions", "Generate tab completion strings.",
             "--line=<line> [--point=<point>]", handler=cmd_cli_completions)
    register("cli cmd-dump", "Dump the list of installed commands, as JSON.", "",
             handler=cmd_cli_cmd_dump)
    register("cli alias", "Retrieve, set, and delete appctl aliases.")
    register("cli alias list", "List available appctl aliases.", "[--format=<format>]",
             handler=cmd_cli_alias_list, defaults={"format": "yaml"})
    register("cli alias add", "Create an alias.",
             "<key> [--set-user=<user>] [--set-url=<url>] [--set-path=<path>] [--grouping=<grouping>]",
             handler=cmd_cli_alias_add)
    register("cli alias delete", "Delete an alias.", "<key>", handler=cmd_cli_alias_delete)

    register("site", "Create, delete, list, and update sites.")
    register("site create", "Create a site.",
             "<site-name> [--type=<type>] [--title=<title>] [--email=<email>] [--porcelain]",
             handler=cmd_site_create, defaults={"type": "standard"})
    register("site delete", "Delete a site.", "<site-name> [--yes] [--keep-tables]",
             alias="rm", handler=cmd_site_delete)
    register("site list", "List all sites.",
             "[--field=<field>] [--fields=<fields>] [--format=<format>]",
             alias="ls", handler=cmd_site_list, defaults={"format": "table"})
    register("site update", "Update one or more fields of a site.",
             "<site-name> [--<field>=<value>]", handler=cmd_site_update)
    register("site activate", "Activate one or more sites.", "<site-name>...",
             handler=cmd_site_activate)
    register("site deactivate", "Deactivate one or more sites.", "<site-name>...",
             handler=cmd_site_deactivate)
    register("site empty", "Empty a site of its content.", "[--uploads] [--yes]",
             handler=cmd_site_empty)
    register("site meta", "Add, update, get, and delete site metadata.")
    register("site meta get", "Get a meta field.", "<site-name> <key> [--format=<format>]",
             handler=cmd_site_meta_get, defaults={"format": "var_export"})
    register("site meta set", "Set a meta field.", "<site-name> <key> <value> [--format=<format>]",
             handler=cmd_site_meta_set, defaults={"format": "plaintext"}, stdin_args=("value",))
    register("site meta delete", "Delete a meta field.", "<site-name> <key> [--all]",
             handler=cmd_site_meta_delete)
    register("site meta list", "List all metadata associated with a site.",
             "<site-name> [--keys=<keys>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_site_meta_list, defaults={"format": "table"})

    register("config", "Generate and read the application configuration file.", alias="cfg")
    register("config get", "Get the value of a specific constant or variable.",
             "<name> [--type=<type>] [--format=<format>]",
             handler=cmd_config_get, defaults={"type": "all", "format": "var_export"})
    register("config set", "Set the value of a specific constant or variable.",
             "<name> <value> [--add] [--raw] [--anchor=<anchor>] [--type=<type>]",
             handler=cmd_config_set, defaults={"type": "all"}, stdin_args=("value",))
    register("config delete", "Delete a specific constant or variable.",
             "<name> [--type=<type>]", handler=cmd_config_delete, defaults={"type": "all"})
    register("config list", "List variables, constants, and file includes.",
             "[<filter>...] [--fields=<fields>] [--format=<format>] [--strict]",
             handler=cmd_config_list, defaults={"format": "table"})
    register("config path", "Get the path to the configuration file.", "",
             handler=cmd_config_path)
    register("config create", "Generate a configuration file.",
             "--dbname=<dbname> --dbuser=<dbuser> [--dbpass=<dbpass>] [--dbhost=<dbhost>] "
             "[--dbprefix=<dbprefix>] [--skip-check] [--force]",
             handler=cmd_config_create, defaults={"dbhost": "localhost", "dbprefix": "app_"})

    register("cache", "Add, remove, fetch, and flush the object cache.")
    register("cache flush", "Flush the object cache.", "", handler=cmd_cache_flush)
    register("cache get", "Get a value from the object cache.", "<key> [<group>]",
             handler=cmd_cache_get, defaults={"group": "default"})
    register("cache set", "Set a value to the object cache.",
             "<key> <value> [<group>] [<expiration>]", handler=cmd_cache_set,
             defaults={"group": "default", "expiration": 0}, stdin_args=("value",))
    register("cache delete", "Remove a value from the object cache.", "<key> [<group>]",
             handler=cmd_cache_delete, defaults={"group": "default"})

    register("db", "Perform basic database operations.")
    register("db create", "Create a new database.", "", handler=cmd_db_create)
    register("db drop", "Delete the existing database.", "[--yes]", handler=cmd_db_drop)
    register("db reset", "Remove all tables from the database.", "[--yes]", handler=cmd_db_reset)
    register("db export", "Export the database to a file or to STDOUT.",
             "[<file>] [--tables=<tables>] [--exclude_tables=<tables>] [--porcelain]",
             handler=cmd_db_export)
    register("db import", "Import a database from a file or from STDIN.",
             "[<file>] [--skip-optimization]", handler=cmd_db_import,
             defaults={"file": "database.sql"})
    register("db query", "Execute a SQL query against the database.", "[<sql>]",
             handler=cmd_db_query, stdin_args=("sql",))
    register("db size", "Display the database name and size.",
             "[--size_format=<format>] [--tables] [--format=<format>]",
             handler=cmd_db_size, defaults={"format": "table"})

    register("option", "Retrieve and set site options.")
    register("option get", "Get the value for an option.", "<key> [--format=<format>]",
             handler=cmd_option_get, defaults={"format": "var_export"})
    register("option add", "Add a new option value.",
             "<key> [<value>] [--format=<format>] [--autoload=<autoload>]",
             handler=cmd_option_add, defaults={"format": "plaintext", "autoload": "yes"},
             stdin_args=("value",))
    register("option update", "Update an option value.",
             "<key> [<value>] [--autoload=<autoload>] [--format=<format>]",
             handler=cmd_option_update, defaults={"format": "plaintext"}, stdin_args=("value",))
    register("option delete", "Delete an option.", "<key>...", handler=cmd_option_delete)
    register("option list", "List options and their values.",
             "[--search=<pattern>] [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_option_list, defaults={"format": "table"})

    register("plugin", "Manage plugins.")
    register("plugin install", "Install one or more plugins.",
             "<plugin|zip|url>... [--version=<version>] [--force] [--activate]",
             handler=cmd_plugin_install)
    register("plugin activate", "Activate one or more plugins.",
             "[<plugin>...] [--all] [--network]", handler=cmd_plugin_activate)
    register("plugin deactivate", "Deactivate one or more plugins.",
             "[<plugin>...] [--uninstall] [--all] [--network]", handler=cmd_plugin_deactivate)
    register("plugin delete", "Delete plugin files without deactivating or uninstalling.",
             "[<plugin>...] [--all]", handler=cmd_plugin_delete)
    register("plugin uninstall", "Uninstall one or more plugins.",
             "[<plugin>...] [--deactivate] [--skip-delete] [--all]", handler=cmd_plugin_uninstall)
    register("plugin update", "Update one or more plugins.",
             "[<plugin>...] [--all] [--format=<format>] [--version=<version>] [--dry-run]",
             handler=cmd_plugin_update, defaults={"format": "table"})
    register("plugin list", "Get a list of plugins.",
             "[--status=<status>] [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_plugin_list, defaults={"format": "table"})
    register("plugin status", "Reveal the status of one or all plugins.", "[<plugin>]",
             handler=cmd_plugin_status)

    register("theme", "Manage themes.")
    register("theme activate", "Activate a theme.", "<theme>", handler=cmd_theme_activate)
    register("theme install", "Install one or more themes.",
             "<theme|zip|url>... [--version=<version>] [--force] [--activate]",
             handler=cmd_theme_install)
    register("theme delete", "Delete one or more themes.", "[<theme>...] [--all] [--force]",
             handler=cmd_theme_delete)
    register("theme list", "Get a list of themes.",
             "[--status=<status>] [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_theme_list, defaults={"format": "table"})

    register("post", "Manage posts, content, and meta.")
    register("post create", "Create a new post.",
             "[--post_title=<title>] [--post_type=<type>] [--post_status=<status>] "
             "[--<field>=<value>] [--porcelain]",
             handler=cmd_post_create, defaults={"post_type": "post", "post_status": "draft"})
    register("post get", "Get details about a post.",
             "<id> [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_post_get, defaults={"format": "table"})
    register("post list", "Get a list of posts.",
             "[--<field>=<value>] [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_post_list, defaults={"format": "table"})
    register("post update", "Update one or more existing posts.",
             "<id>... [--<field>=<value>]", handler=cmd_post_update)
    register("post delete", "Delete an existing post.", "<id>... [--force] [--defer-term-counting]",
             handler=cmd_post_delete)

    register("user", "Manage users, along with their roles, capabilities, and meta.")
    register("user create", "Create a new user.",
             "<user-login> <user-email> [--role=<role>] [--user_pass=<password>] "
             "[--display_name=<name>] [--send-email] [--porcelain]",
             handler=cmd_user_create, defaults={"role": "subscriber"})
    register("user delete", "Delete one or more users.",
             "<user>... [--network] [--reassign=<user-id>] [--yes]", handler=cmd_user_delete)
    register("user get", "Get details about a user.",
             "<user> [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_user_get, defaults={"format": "table"})
    register("user list", "List users.",
             "[--role=<role>] [--field=<field>] [--fields=<fields>] [--format=<format>]",
             handler=cmd_user_list, defaults={"format": "table"})
    register("user update", "Update an existing user.",
             "<user>... [--user_pass=<password>] [--<field>=<value>] [--skip-email]",
             handler=cmd_user_update)


build_registry()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_CONFIG_FILES = ("appctl.local.yml", "appctl.yml")
# Values written to the global config file when they are missing.
AUTO_CONFIG = (("locale", "en_US"), ("installer_version", "stable"))


def root_dir():
    return os.environ.get("APPCTL_ROOT_DIR") or os.path.join(os.path.expanduser("~"), ".appctl")


def packages_dir():
    return os.environ.get("APPCTL_PACKAGES_DIR") or os.path.join(root_dir(), "packages")


def global_config_path():
    return os.environ.get("APPCTL_CONFIG_PATH") or os.path.join(root_dir(), "config", "config.yml")


def project_config_path():
    """Search upward from the working directory for a project config file."""
    try:
        directory = os.getcwd()
    except OSError:
        return None
    while True:
        for name in PROJECT_CONFIG_FILES:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent


def absolutize(path, base_dir):
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(base_dir, path))


def read_yaml_file(path):
    """Return the mapping stored in ``path`` ({} when missing or empty)."""
    with open(path, encoding="utf-8") as handle:
        data = yaml_load(handle.read())
    return data if isinstance(data, dict) else {}


def ensure_global_config():
    """Add missing auto-created values (locale, installer_version) to the global config."""
    path = global_config_path()
    explicit = bool(os.environ.get("APPCTL_CONFIG_PATH") or os.environ.get("APPCTL_ROOT_DIR"))
    text = ""
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        existing = yaml_load(text)
    except YamlError:
        return
    except (OSError, UnicodeDecodeError) as exc:
        if explicit:
            error("Unable to read the global config file '%s': %s."
                  % (path, getattr(exc, "strerror", None) or exc))
        return
    if existing is None:
        existing = {}
    if not isinstance(existing, dict):
        return
    missing = [(key, value) for key, value in AUTO_CONFIG if key not in existing]
    if not missing:
        return
    if existing and text.lstrip().startswith("{"):
        merged = dict(existing)
        merged.update(missing)
        content, mode = "\n".join(yaml_dump_lines(merged)) + "\n", "w"
    else:
        content = "\n" if text and not text.endswith("\n") else ""
        content += "".join("%s: %s\n" % (key, value) for key, value in missing)
        mode = "a"
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, mode, encoding="utf-8") as handle:
            handle.write(content)
    except OSError as exc:
        if explicit:
            error("Unable to write the global config file '%s': %s."
                  % (path, exc.strerror or exc))
        debug("Unable to write the global config file '%s'." % path, "bootstrap")


ALIAS_RE = re.compile(r"^@[A-Za-z0-9_.\-]+$")
ALIAS_KEYS = ("user", "url", "path", "ssh", "http", "proxyjump", "key")
ALL_ALIAS_DESCRIPTION = "Run command against every registered alias."


def is_alias_name(name):
    return isinstance(name, str) and ALIAS_RE.match(name) is not None


def parse_alias(value, base_dir=None):
    """Normalize an alias definition: a dict of connection values or a group list."""
    if isinstance(value, list):
        return [item if isinstance(item, str) else str(item) for item in value]
    alias = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if item is None:
                continue
            if key in ALIAS_KEYS or (key in GLOBAL_SPEC and GLOBAL_SPEC[key]["file"]):
                alias[key] = item
        if base_dir and isinstance(alias.get("path"), str) and "ssh" not in alias:
            alias["path"] = absolutize(alias["path"], base_dir)
    return alias


class ConfigLoader:
    """Accumulate global parameters and aliases from config files."""

    def __init__(self):
        self.config = {}
        self.aliases = {}

    def merge_file(self, path, chain=()):
        path = os.path.abspath(path)
        if path in chain or not os.path.isfile(path):
            return
        try:
            data = read_yaml_file(path)
        except (OSError, UnicodeDecodeError, YamlError) as exc:
            warning("Unable to parse config file '%s': %s" % (path, exc))
            return
        base_dir = os.path.dirname(path)
        meta = data.get("_") if isinstance(data.get("_"), dict) else {}
        inherit = meta.get("inherit")
        if isinstance(inherit, str) and inherit:
            parent = absolutize(inherit, base_dir)
            if not os.path.isfile(parent) and os.path.isfile(os.path.abspath(inherit)):
                parent = os.path.abspath(inherit)
            self.merge_file(parent, chain + (path,))
        merge = bool(meta.get("merge"))
        for key, value in data.items():
            if key == "_":
                continue
            if is_alias_name(key):
                self.aliases[key] = parse_alias(value, base_dir)
                continue
            spec = GLOBAL_SPEC.get(key)
            if spec is None or not spec["file"]:
                continue
            if key == "path" and isinstance(value, str):
                value = absolutize(value, base_dir)
            if spec["multiple"] and value is not None and not isinstance(value, list):
                value = [value]
            current = self.config.get(key)
            if merge and isinstance(current, list) and isinstance(value, list):
                value = current + value
            self.config[key] = value

    def merge_runtime_aliases(self, encoded):
        try:
            data = json.loads(encoded)
        except ValueError:
            warning("APPCTL_RUNTIME_ALIAS does not contain valid JSON.")
            return
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            if is_alias_name(key):
                self.aliases[key] = parse_alias(value)


def load_config():
    """Load global and project config files. Returns the populated loader."""
    loader = ConfigLoader()
    global_path = global_config_path()
    if os.path.isfile(global_path):
        debug("Using global config: %s" % global_path, "bootstrap")
        loader.merge_file(global_path)
    else:
        debug("No readable global config found", "bootstrap")
    project_path = project_config_path()
    if project_path:
        debug("Using project config: %s" % project_path, "bootstrap")
        loader.merge_file(project_path)
    else:
        debug("No project config found", "bootstrap")
    runtime_aliases = os.environ.get("APPCTL_RUNTIME_ALIAS")
    if runtime_aliases:
        loader.merge_runtime_aliases(runtime_aliases)
    if loader.aliases and "@all" not in loader.aliases:
        loader.aliases = dict([("@all", ALL_ALIAS_DESCRIPTION)] + list(loader.aliases.items()))
    Runtime.global_config_path = global_path
    Runtime.project_config_path = project_path
    Runtime.aliases = loader.aliases
    return loader


def compose_config(file_config, alias_config, runtime):
    """Merge defaults < config files < alias < runtime flags."""
    config = {name: (list(spec["default"]) if isinstance(spec["default"], list)
                     else spec["default"]) for name, spec in GLOBAL_SPEC.items()}
    config.update(file_config)
    config.update(alias_config)
    config.update(runtime)
    if runtime.get("blog") not in (None, True, False) and "url" not in runtime:
        config["url"] = runtime["blog"]
    return config


def disabled_commands():
    value = Runtime.config.get("disabled_commands") or []
    if not isinstance(value, list):
        value = [value]
    return {" ".join(str(item).split()) for item in value if item is not None}


def is_command_disabled(command):
    disabled = disabled_commands()
    node = command
    while node is not None and node.parent is not None:
        if node.path in disabled:
            return True
        node = node.parent
    return False


# ---------------------------------------------------------------------------
# Remote execution
# ---------------------------------------------------------------------------

SSH_URL_RE = re.compile(
    r"^(?:(docker|docker-compose|docker-compose-run|ssh|vagrant):(?://)?)?"
    r"(?:([^@:/]+)@)?([^:/~]+)(?::(\d*))?((?:/|~).*)?$")


def escapeshellarg(value):
    return "'" + str(value).replace("'", "'\\''") + "'"


def parse_ssh_url(url):
    match = SSH_URL_RE.match(str(url))
    if not match:
        return {"scheme": None, "user": None, "host": str(url), "port": None, "path": None}
    scheme, user, host, port, path = match.groups()
    return {"scheme": scheme, "user": user, "host": host, "port": port or None,
            "path": path or None}


def generate_ssh_command(bits, command, config):
    is_tty = sys.stdout.isatty() and not config.get("skip-tty")
    scheme = bits["scheme"] or "ssh"
    user_opt = "--user %s " % escapeshellarg(bits["user"]) if bits["user"] else ""
    workdir_opt = "--workdir %s " % escapeshellarg(bits["path"]) if bits["path"] else ""
    if scheme == "docker":
        return "docker exec %s%s%s%s sh -c %s" % (
            user_opt, workdir_opt, "-t " if is_tty else "", escapeshellarg(bits["host"]),
            escapeshellarg(command))
    if scheme == "docker-compose":
        return "docker-compose exec %s%s%s%s sh -c %s" % (
            user_opt, workdir_opt, "" if is_tty else "-T ", escapeshellarg(bits["host"]),
            escapeshellarg(command))
    if scheme == "docker-compose-run":
        return "docker-compose run %s%s%s%s sh -c %s" % (
            user_opt, workdir_opt, "" if is_tty else "-T ", escapeshellarg(bits["host"]),
            escapeshellarg(command))
    if scheme == "vagrant":
        return "vagrant ssh -c %s %s" % (escapeshellarg(command), escapeshellarg(bits["host"]))
    options = []
    if config.get("proxyjump"):
        options.append("-J %s" % escapeshellarg(config["proxyjump"]))
    if bits["port"]:
        options.append("-p %d" % int(bits["port"]))
    if config.get("key"):
        options.append("-i %s" % escapeshellarg(config["key"]))
    options.append("-t" if is_tty else "-T")
    options.append("-vvv" if Runtime.debug else "-q")
    host = "%s@%s" % (bits["user"], bits["host"]) if bits["user"] else bits["host"]
    return "ssh %s %s %s" % (" ".join(options), escapeshellarg(host), escapeshellarg(command))


def run_remote(invocation, config, alias, alias_config):
    """Run the invocation on the endpoint named by the ``ssh`` config value."""
    import subprocess

    bits = parse_ssh_url(config["ssh"])
    pre_cmd = os.environ.get("APPCTL_SSH_PRE_CMD", "")
    if pre_cmd:
        warning("APPCTL_SSH_PRE_CMD found, executing the following command(s) on the "
                "remote machines:")
        sys.stderr.write(pre_cmd + "\n")
        pre_cmd = pre_cmd.rstrip().rstrip(";") + "; "
    if bits["path"] and (bits["scheme"] or "ssh") in ("ssh", "vagrant"):
        pre_cmd += "cd %s; " % escapeshellarg(bits["path"])
    env_vars = "%s=1 " % STRICT_ENV if os.environ.get(STRICT_ENV) else ""
    binary = PROG
    if alias:
        runtime_alias = {k: v for k, v in alias_config.items() if k != "ssh"}
        if runtime_alias:
            binary = "APPCTL_RUNTIME_ALIAS=%s %s %s" % (
                escapeshellarg(json.dumps({alias: runtime_alias})), PROG, alias)
    args = [arg for arg in invocation.argv if not arg.startswith("--ssh=")]
    command = pre_cmd + env_vars + binary
    if args:
        command += " " + " ".join(escapeshellarg(arg) for arg in args)
    full_command = generate_ssh_command(bits, command, config)
    debug("Running SSH command: %s" % full_command, "ssh")
    sys.stdout.flush()
    sys.stderr.flush()
    code = subprocess.call(full_command, shell=True)
    if code == 255:
        error("Cannot connect over SSH using provided configuration.", 255)
    return code


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

class Invocation:
    """The parsed command line, shared by every alias the command runs against."""

    def __init__(self, argv, positionals, assoc_list, runtime, loader):
        self.argv = argv
        self.positionals = positionals
        self.assoc_list = assoc_list
        self.runtime = runtime
        self.file_config = loader.config
        self.aliases = loader.aliases


def extract_alias(argv):
    """Remove and return a leading ``@alias`` positional from ``argv``."""
    for index, token in enumerate(argv):
        if token == "--":
            return None
        if parse_token(token) is not None:
            continue
        if is_alias_name(token):
            del argv[index]
            return token
        return None
    return None


def apply_runtime_config(config, runtime):
    Runtime.config = config
    Runtime.quiet = bool(runtime.get("quiet"))
    value = runtime.get("debug")
    Runtime.debug = value not in (None, False)
    Runtime.debug_group = value if isinstance(value, str) and value else None


def dispatch(alias, invocation, stack=()):
    """Run the invocation, resolving ``alias`` (and alias groups) first."""
    aliases = invocation.aliases
    if alias is None:
        return execute(invocation, None, {})
    if alias == "@all" and "@all" not in aliases:
        error("Cannot use '@all' when no aliases are registered.")
    if alias == "@all" and isinstance(aliases["@all"], str):
        names = sorted((name for name in aliases if name != "@all"), key=sort_key)
        return run_alias_group(names, invocation, stack + (alias,))
    if alias not in aliases:
        message = "Alias '%s' not found." % alias
        suggestion = get_suggestion(alias, aliases.keys(), synonyms=False)
        if suggestion:
            message += "\nDid you mean '%s'?" % suggestion
        error(message)
    definition = aliases[alias]
    if isinstance(definition, list):
        members = []
        for name in definition:
            if name not in members:
                members.append(name)
        invalid = [name for name in members if name not in aliases]
        if invalid:
            error("Group '%s' contains one or more invalid aliases: %s."
                  % (alias, ", ".join(invalid)))
        return run_alias_group(members, invocation, stack + (alias,))
    return execute(invocation, alias, definition if isinstance(definition, dict) else {})


def run_alias_group(names, invocation, stack):
    code = 0
    for name in names:
        if name in stack:
            continue
        log(name)
        try:
            result = dispatch(name, invocation, stack)
        except AppctlExit as exc:
            result = exc.code
        sys.stdout.flush()
        if result:
            code = result
    return code


def execute(invocation, alias, alias_config):
    config = compose_config(invocation.file_config, alias_config, invocation.runtime)
    apply_runtime_config(config, invocation.runtime)
    if alias:
        debug("Using alias: %s" % alias, "bootstrap")
    debug("Resolved config: %s" % json.dumps(config, sort_keys=True, default=str), "bootstrap")

    if config.get("ssh"):
        return run_remote(invocation, config, alias, alias_config)

    positionals = invocation.positionals
    if not positionals:
        show_root_help()
        return 0

    command, remaining = resolve_command(positionals)
    debug("Running command: %s" % command.path, "commands")

    if command.handler is None:
        command.show_usage()
        return 0

    args, assoc = validate_and_prepare(command, remaining, invocation.assoc_list)
    command.handler(args, assoc)
    return 0


def is_completion(positionals):
    """Tab completion invocations never write to the log file."""
    return positionals[:2] == ["cli", "completions"]


def run(argv):
    strict = bool(os.environ.get(STRICT_ENV))
    argv = list(argv)
    alias = extract_alias(argv)
    tokens = rewrite_args(argv)
    positionals, assoc_list, runtime = split_args(tokens, strict)
    FileLog.enabled = not is_completion(positionals)
    log_invocation(argv if alias is None else [alias] + argv)
    apply_runtime_config(dict(runtime), runtime)
    if Runtime.debug:
        debug("Runtime config: %s" % json.dumps(runtime, sort_keys=True), "bootstrap")
    for name in runtime:
        if GLOBAL_SPEC[name]["deprecated"]:
            warning("The --%s global parameter is deprecated." % name)

    ensure_global_config()
    loader = load_config()
    invocation = Invocation(argv, positionals, assoc_list, runtime, loader)
    return dispatch(alias, invocation)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    Runtime.start_time = time.time()
    try:
        code = run(argv)
    except AppctlExit as exc:
        code = exc.code
    except BrokenPipeError:
        code = 0
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
