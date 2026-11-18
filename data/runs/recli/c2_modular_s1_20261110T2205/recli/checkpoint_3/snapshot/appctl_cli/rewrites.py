"""Argument rewrites applied before dispatch.

* ``<command> --help`` becomes ``help <command>``.
* ``--version`` (with no command) becomes ``cli version``.
"""

from .arguments import END_OF_OPTIONS, is_assoc_token, parse_assoc_token
from .runtime_config import is_global_parameter


def _split_options(argv):
    """Return ``(head, tail)``; ``tail`` holds tokens after ``--``."""
    if END_OF_OPTIONS in argv:
        index = argv.index(END_OF_OPTIONS)
        return argv[:index], argv[index + 1:]
    return argv, []


def rewrite_help(argv):
    head, tail = _split_options(argv)
    if "--help" not in head:
        return argv
    positional = [t for t in head if not is_assoc_token(t)] + tail
    # Keep global parameters (ahead of 'help' so they stay global in strict
    # mode); command-specific parameters are irrelevant to help output.
    global_flags = [
        t for t in head
        if t != "--help" and is_assoc_token(t) and is_global_parameter(parse_assoc_token(t)[0])
    ]
    return global_flags + ["help"] + positional


def rewrite_version(argv):
    head, tail = _split_options(argv)
    if "--version" not in head or tail or any(not is_assoc_token(t) for t in head):
        return argv
    rewritten = []
    for token in head:
        rewritten.extend(["cli", "version"] if token == "--version" else [token])
    return rewritten


def apply_rewrites(argv):
    return rewrite_version(rewrite_help(list(argv)))
