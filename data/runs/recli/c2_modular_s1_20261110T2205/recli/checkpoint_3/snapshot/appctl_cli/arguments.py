"""Splitting raw argv into positional, associative and global arguments."""

from dataclasses import dataclass, field

from .runtime_config import is_global_parameter

END_OF_OPTIONS = "--"


def is_assoc_token(token):
    """True for ``--key``, ``--key=value`` and ``--no-key`` tokens."""
    return token.startswith("--") and len(token) > 2


def parse_assoc_token(token):
    """Return ``(key, value)`` for an associative token.

    ``--key=value`` yields the string value, ``--no-key`` yields ``False``
    and a bare ``--key`` yields ``True``.
    """
    body = token[2:]
    if "=" in body:
        key, value = body.split("=", 1)
        return key, value
    if body.startswith("no-"):
        return body[3:], False
    return body, True


@dataclass
class ParsedArguments:
    positional: list = field(default_factory=list)
    assoc: dict = field(default_factory=dict)
    runtime: dict = field(default_factory=dict)


def parse_argv(argv, strict=False):
    """Classify every argv token.

    Global parameters become runtime configuration. In strict mode only
    those appearing before the first positional token are treated as
    global; afterwards every argument is command-specific.
    """
    parsed = ParsedArguments()
    end_of_options = False
    seen_positional = False
    for token in argv:
        if not end_of_options and token == END_OF_OPTIONS:
            end_of_options = True
            continue
        if end_of_options or not is_assoc_token(token):
            parsed.positional.append(token)
            seen_positional = True
            continue
        key, value = parse_assoc_token(token)
        if is_global_parameter(key) and not (strict and seen_positional):
            parsed.runtime[key] = value
        else:
            parsed.assoc[key] = value
    return parsed
