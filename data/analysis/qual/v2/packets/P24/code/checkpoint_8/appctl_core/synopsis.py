"""Synopsis grammar.

Secret: the textual grammar of synopsis strings and how each part is
classified (positional, keyed parameter, flag, negatable flag, generic keyed
field, malformed; optional and repeating modifiers).
"""

import re

_NAME = r"[A-Za-z0-9][\w-]*"
_PLACEHOLDER = r"[\w|.-]+"

_POSITIONAL = re.compile(rf"^<({_PLACEHOLDER})>$")
_GENERIC = re.compile(rf"^--<({_PLACEHOLDER})>=<({_PLACEHOLDER})>$")
_KEYED = re.compile(rf"^--({_NAME})=<({_PLACEHOLDER})>$")
_KEYED_OPTIONAL_VALUE = re.compile(rf"^--({_NAME})\[=<({_PLACEHOLDER})>\]$")
_FLAG = re.compile(rf"^--({_NAME})$")
_NEGATABLE_FLAG = re.compile(rf"^--\[no-\]({_NAME})$")

_POSITIONAL_KIND = "positional"
_KEYED_KIND = "keyed"
_FLAG_KIND = "flag"
_GENERIC_KIND = "generic"
_MALFORMED_KIND = "malformed"

_REPEAT = "..."


class _Part:
    __slots__ = ("text", "kind", "name", "optional", "repeating", "value_optional")

    def __init__(self, text, kind, name=None, optional=False, repeating=False,
                 value_optional=False):
        self.text = text
        self.kind = kind
        self.name = name
        self.optional = optional
        self.repeating = repeating
        self.value_optional = value_optional


def _outer_brackets(text):
    """True when the leading '[' is closed by the trailing ']'."""
    if not (text.startswith("[") and text.endswith("]")):
        return False
    depth = 0
    for index, char in enumerate(text):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0 and index != len(text) - 1:
                return False
    return depth == 0


def _parse_part(text):
    core = text
    optional = repeating = False
    if core.endswith(_REPEAT):
        repeating, core = True, core[: -len(_REPEAT)]
    if _outer_brackets(core):
        optional, core = True, core[1:-1]
        if core.endswith(_REPEAT):
            repeating, core = True, core[: -len(_REPEAT)]

    def part(kind, name=None, value_optional=False):
        return _Part(text, kind, name, optional, repeating, value_optional)

    match = _POSITIONAL.match(core)
    if match:
        return part(_POSITIONAL_KIND, match.group(1))
    match = _GENERIC.match(core)
    if match:
        return part(_GENERIC_KIND, match.group(1))
    match = _KEYED.match(core)
    if match:
        return part(_KEYED_KIND, match.group(1))
    match = _KEYED_OPTIONAL_VALUE.match(core)
    if match:
        return part(_KEYED_KIND, match.group(1), value_optional=True)
    match = _FLAG.match(core) or _NEGATABLE_FLAG.match(core)
    if match:
        return part(_FLAG_KIND, match.group(1))
    return _Part(text, _MALFORMED_KIND)


class Synopsis:
    """A parsed synopsis that answers questions about accepted arguments."""

    OK = "ok"
    UNKNOWN = "unknown"
    NEEDS_VALUE = "needs-value"
    TAKES_NO_VALUE = "takes-no-value"

    def __init__(self, text=""):
        self._parts = [_parse_part(p) for p in (text or "").split()]
        self._options = {}
        for part in self._parts:
            if part.kind in (_KEYED_KIND, _FLAG_KIND):
                self._options[part.name] = part

    def text(self):
        return " ".join(part.text for part in self._parts)

    def parts(self):
        """Every part in declaration order (``text``, ``kind``, ``name``,
        ``optional``, ``repeating``, ``value_optional``)."""
        return list(self._parts)

    def malformed_parts(self):
        return [p.text for p in self._parts if p.kind == _MALFORMED_KIND]

    def _positionals(self):
        return [p for p in self._parts if p.kind == _POSITIONAL_KIND]

    def required_positional_count(self):
        return sum(1 for p in self._positionals() if not p.optional)

    def positional_limit(self):
        """Maximum number of positional words, or ``None`` if unbounded."""
        positionals = self._positionals()
        if any(p.repeating for p in positionals):
            return None
        return len(positionals)

    def positional_names(self):
        return [p.name for p in self._positionals()]

    def option_names(self):
        """Declared keyed-parameter and flag names, in declaration order."""
        return list(self._options)

    def required_option_names(self):
        return [name for name, p in self._options.items() if not p.optional]

    def accepts_any_option(self):
        return any(p.kind == _GENERIC_KIND for p in self._parts)

    def requires_generic_option(self):
        """Name of a mandatory generic field placeholder, or ``None``."""
        for p in self._parts:
            if p.kind == _GENERIC_KIND and not p.optional:
                return p.name
        return None

    def interpret(self, name, value):
        """Interpret a supplied option.

        ``value`` is the supplied string or ``None`` when no ``=`` was given.
        Returns ``(key, value, status)`` where status is one of the class
        constants. Flags yield booleans; keyed parameters yield strings.
        """
        part = self._options.get(name)
        if part is not None:
            if part.kind == _FLAG_KIND:
                if value is None:
                    return name, True, self.OK
                return name, None, self.TAKES_NO_VALUE
            if value is None and part.value_optional:
                return name, True, self.OK
            if value is None or value == "":
                return name, None, self.NEEDS_VALUE
            return name, value, self.OK
        if name.startswith("no-") and value is None:
            negated = self._options.get(name[3:])
            if negated is not None and negated.kind == _FLAG_KIND:
                return negated.name, False, self.OK
        if self.accepts_any_option():
            return name, (True if value is None else value), self.OK
        return name, None, self.UNKNOWN
