"""Parsing and classification of command synopsis strings."""

import re
from dataclasses import dataclass
from typing import Optional

POSITIONAL = "positional"
ASSOC = "assoc"
FLAG = "flag"
GENERIC = "generic"
UNKNOWN = "unknown"

GENERIC_TOKEN = "--<field>=<value>"

_NAME = r"[a-z0-9_-]+"
_VALUE = r"[a-zA-Z0-9_|,-]+"
_POSITIONAL_RE = re.compile(rf"^<({_VALUE})>$")
_PARAM_RE = re.compile(rf"^--(\[no-\])?({_NAME})")
_VALUE_RE = re.compile(rf"^=<({_VALUE})>$")


@dataclass(frozen=True)
class SynopsisToken:
    """One classified token of a synopsis string."""

    token: str
    type: str
    name: Optional[str] = None
    optional: bool = False
    repeating: bool = False
    value_name: Optional[str] = None
    value_optional: bool = False
    negatable: bool = False

    @property
    def is_positional(self):
        return self.type == POSITIONAL

    @property
    def is_parameter(self):
        """True for named ``--key=<value>`` and ``--flag`` tokens."""
        return self.type in (ASSOC, FLAG)


def _strip_optional(text):
    if len(text) >= 2 and text.startswith("[") and text.endswith("]"):
        return True, text[1:-1]
    return False, text


def _strip_repeating(text):
    if text.endswith("..."):
        return True, text[:-3]
    return False, text


def classify_token(token):
    """Classify a single synopsis token."""
    optional, body = _strip_optional(token)
    repeating, body = _strip_repeating(body)
    unknown = SynopsisToken(token=token, type=UNKNOWN)

    if body == GENERIC_TOKEN:
        return SynopsisToken(token, GENERIC, optional=optional, repeating=repeating)

    match = _POSITIONAL_RE.match(body)
    if match:
        return SynopsisToken(token, POSITIONAL, name=match.group(1),
                             optional=optional, repeating=repeating)

    match = _PARAM_RE.match(body)
    if not match:
        return unknown
    negatable = bool(match.group(1))
    name = match.group(2)
    rest = body[match.end():]

    if rest == "":
        # Boolean flags are by nature optional.
        if not optional:
            return unknown
        return SynopsisToken(token, FLAG, name=name, optional=True,
                             repeating=repeating, negatable=negatable)

    if negatable:
        return unknown
    value_optional, rest = _strip_optional(rest)
    value_match = _VALUE_RE.match(rest)
    if not value_match:
        return unknown
    return SynopsisToken(token, ASSOC, name=name, optional=optional,
                         repeating=repeating, value_name=value_match.group(1),
                         value_optional=value_optional)


def parse_synopsis(synopsis):
    """Split a synopsis string into classified tokens."""
    return [classify_token(token) for token in (synopsis or "").split()]


def invalid_tokens(tokens):
    """Return the raw text of every malformed token."""
    return [t.token for t in tokens if t.type == UNKNOWN]
