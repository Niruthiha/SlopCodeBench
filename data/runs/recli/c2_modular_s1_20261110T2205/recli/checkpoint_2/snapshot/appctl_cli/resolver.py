"""Hierarchical resolution of positional tokens to a command."""

from . import PROGRAM_NAME
from .errors import CommandNotFoundError
from .suggest import get_suggestion


def _with_suggestion(message, typed, parent):
    suggestion = get_suggestion(typed, parent.subcommand_names())
    if suggestion:
        message += f"\nDid you mean '{suggestion}'?"
    return message


def not_found_error(typed, parent):
    if parent.is_root:
        message = (
            f"'{typed}' is not a registered {PROGRAM_NAME} command. "
            f"See '{PROGRAM_NAME} help' for available commands."
        )
    else:
        name = parent.full_name
        message = (
            f"'{typed}' is not a registered subcommand of '{name}'. "
            f"See '{PROGRAM_NAME} help {name}' for available subcommands."
        )
    return CommandNotFoundError(_with_suggestion(message, typed, parent))


def resolve(root, tokens):
    """Walk the tree and return ``(command, remaining_tokens)``.

    Tokens keep matching subcommands (by name or alias) until the deepest
    command is found. If the next token does not match, a command with a
    handler receives it as an argument; otherwise it is an error.
    """
    command = root
    index = 0
    while index < len(tokens) and command.has_subcommands:
        child = command.find_subcommand(tokens[index])
        if child is None:
            if command.is_runnable and not command.is_root:
                break
            raise not_found_error(tokens[index], command)
        command = child
        index += 1
    return command, list(tokens[index:])


def try_resolve(root, tokens):
    """Like :func:`resolve` but return ``None`` instead of raising."""
    try:
        return resolve(root, tokens)
    except CommandNotFoundError:
        return None
