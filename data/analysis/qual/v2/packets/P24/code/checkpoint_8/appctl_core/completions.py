"""Tab completion.

Secret: how the command line left of the cursor is split into words, how
an alias or ``help`` prefix is skipped, how the words are walked down the
command tree, which suggestions (subcommands, aliases, options, the file
marker) apply at the cursor, how they are filtered, ordered and laid out
for each shell.
"""

import shlex

from . import config_spec

SHELLS = ("bash", "zsh")
FILE_MARKER = "<file>"
_ALIAS_PREFIX = "@"
_ALIAS_DESCRIPTION = "Alias"


def _sort_key(text):
    return (text.casefold(), text)


def _split(line):
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()


def _is_file_positional(name):
    return name == "file" or name.endswith("-file")


def _option_suggestion(part):
    """``--name=`` for options needing a value, ``--name`` otherwise."""
    if part.kind == "keyed" and not part.value_optional:
        return f"--{part.name}="
    return f"--{part.name}"


def _describe_option(part, defaults):
    text = part.text.strip("[]").rstrip(".")
    default = defaults.get(part.name)
    return f"{text} (default: {default})" if default is not None else text


def _global_options():
    synopsis = config_spec.runtime_synopsis()
    descriptions = {p.name: p.description for p in config_spec.params()}
    return [(part, descriptions.get(part.name, "")) for part in synopsis.parts()
            if part.kind in ("keyed", "flag")]


def _given_options(words):
    given = set()
    for word in words:
        if word.startswith("--") and len(word) > 2:
            name = word[2:].split("=", 1)[0]
            given.add(name)
            if name.startswith("no-"):
                given.add(name[3:])
    return given


def suggestions(tree, line, aliases=None):
    """``[(suggestion, description)]`` completing ``line`` (the text left of
    the cursor), sorted alphabetically."""
    words = _split(line)
    current = "" if not line or line[-1].isspace() else (words.pop() if words else "")
    words = words[1:]  # the program name
    aliases = dict(aliases or {})
    offer_aliases = True
    if words and words[0].startswith(_ALIAS_PREFIX):
        words = words[1:]
        offer_aliases = False
    elif words and words[0] == "help":
        words = words[1:]
        offer_aliases = False
    node = tree.root
    for word in words:
        if word.startswith("-"):
            continue
        child = node.find_child(word)
        if child is None:
            if node.is_runnable() and not node.is_root():
                break
            return []
        node = child
    found = {}
    given = _given_options(words)
    if node.has_children() or node.is_root():
        for child in node.children():
            found[child.name] = child.description
        if node.is_root() and offer_aliases:
            for name, definition in aliases.items():
                found[name] = (definition if isinstance(definition, str)
                               else _ALIAS_DESCRIPTION)
        if current.startswith("-"):
            for part, description in _global_options():
                if part.name not in given:
                    found[_option_suggestion(part)] = description
    else:
        synopsis = node.synopsis
        if any(_is_file_positional(name) for name in synopsis.positional_names()):
            return [(FILE_MARKER, "File path")] if FILE_MARKER.startswith(current) else []
        defaults = node.defaults()
        for part in synopsis.parts():
            if part.kind in ("keyed", "flag") and part.name not in given:
                found[_option_suggestion(part)] = _describe_option(part, defaults)
        for part, description in _global_options():
            if part.name not in given:
                found.setdefault(_option_suggestion(part), description)
    matches = [(name, desc) for name, desc in found.items() if name.startswith(current)]
    return sorted(matches, key=lambda item: _sort_key(item[0]))


def _zsh_escape(text):
    return text.replace("\\", "\\\\").replace(":", "\\:")


def render(items, shell="bash"):
    """One suggestion per line; zsh lines carry ``name:description``."""
    if shell == "zsh":
        return [f"{_zsh_escape(name)}:{' '.join(str(desc or '').split())}"
                for name, desc in items]
    return [name for name, _ in items]

