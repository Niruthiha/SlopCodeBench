"""Lexical syntax of the command line.

Secret: how raw argv strings are split into option tokens (``--key=value``,
``--flag``) and positional words, including the ``--`` terminator.
"""


class Token:
    """One lexical unit of the command line."""

    __slots__ = ("_text", "_name", "_value", "_option")

    def __init__(self, text, name=None, value=None, option=False):
        self._text = text
        self._name = name
        self._value = value
        self._option = option

    def is_option(self):
        return self._option

    @property
    def text(self):
        """The token exactly as the user typed it."""
        return self._text

    @property
    def name(self):
        """Option name without leading dashes (``None`` for positionals)."""
        return self._name

    @property
    def value(self):
        """Option value as a string, or ``None`` when no ``=`` was given."""
        return self._value

    def __repr__(self):
        return f"Token({self._text!r})"


def positional(text):
    """Build a positional word token."""
    return Token(text)


def lex(argv):
    """Split raw argv strings into tokens."""
    result = []
    options_ended = False
    for raw in argv:
        if options_ended:
            result.append(positional(raw))
        elif raw == "--":
            options_ended = True
        elif raw.startswith("--") and len(raw) > 2:
            body = raw[2:]
            if "=" in body:
                name, value = body.split("=", 1)
            else:
                name, value = body, None
            result.append(Token(raw, name, value, option=True))
        else:
            result.append(positional(raw))
    return result
