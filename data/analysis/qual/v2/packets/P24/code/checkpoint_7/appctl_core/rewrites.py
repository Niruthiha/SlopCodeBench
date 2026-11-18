"""Convenience rewrites applied before dispatch.

Secret: which shortcut spellings are rewritten into canonical commands and
how — currently ``<command> --help`` becomes ``help <command>`` and a bare
``--version`` becomes ``cli version``.
"""

from . import tokens as _tokens


def _is_bare_flag(token, name):
    return token.is_option() and token.name == name and token.value is None


def _rewrite_version(items):
    if any(not t.is_option() for t in items):
        return items
    if not any(_is_bare_flag(t, "version") for t in items):
        return items
    kept = [t for t in items if not _is_bare_flag(t, "version")]
    return kept + [_tokens.positional("cli"), _tokens.positional("version")]


def _rewrite_help(items):
    if not any(_is_bare_flag(t, "help") for t in items):
        return items
    kept = [t for t in items if not _is_bare_flag(t, "help")]
    help_word = _tokens.positional("help")
    for index, token in enumerate(kept):
        if not token.is_option():
            return kept[:index] + [help_word] + kept[index:]
    return kept + [help_word]


def apply(items):
    """Return a new token list with all rewrites applied."""
    return _rewrite_help(_rewrite_version(list(items)))
