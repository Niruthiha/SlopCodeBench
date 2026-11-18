"""Command resolution.

Secret: how positional words are walked down the command tree, and when
leftover words become arguments of the matched command rather than unknown
subcommands.
"""

from . import messages as _messages
from .errors import CliError
from .suggest import suggest


def resolve(tree, words, disabled=()):
    """Find the deepest command matching the leading ``words``.

    Returns ``(node, remaining_words)``. Raises ``CliError`` for an unknown
    top-level command, an unknown subcommand under a group that cannot
    itself run, or a command whose path is listed in ``disabled``.
    """
    disabled = set(disabled)
    node = tree.root
    words = list(words)
    consumed = 0
    for word in words:
        if not node.has_children():
            break
        child = node.find_child(word)
        if child is None:
            if node.is_runnable() and not node.is_root():
                break
            suggestion = suggest(word, node.child_names())
            if node.is_root():
                raise CliError(_messages.unregistered_command(word, suggestion))
            raise CliError(_messages.unregistered_subcommand(
                word, node.path, suggestion))
        node = child
        consumed += 1
        if node.path in disabled:
            raise CliError(_messages.command_disabled(node.path))
    return node, words[consumed:]
