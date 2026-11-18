"""Help and usage layout.

Secret: how help listings, command help pages and usage lines are laid out:
section order, column alignment and wording of the surrounding text.
"""

from .messages import program_name


def _columns(nodes):
    width = max((len(n.name) for n in nodes), default=0)
    return "\n".join(f"  {n.name.ljust(width)}  {n.description}".rstrip()
                     for n in nodes)


def _invocation(node):
    """``appctl <path> <synopsis>`` for one command."""
    words = [program_name(), node.path]
    if node.has_children() and not node.is_runnable():
        words.append("<command>")
    else:
        words.append(node.synopsis.text())
    return " ".join(w for w in words if w)


def top_level_help(tree):
    prog = program_name()
    return (
        f"usage: {prog} <command> [<subcommand>] [<args>] [--<flags>]\n"
        "\n"
        "Available commands:\n"
        "\n"
        f"{_columns(tree.root.children())}\n"
        "\n"
        f"See '{prog} help <command>' for more information on a specific command."
    )


def usage_line(node):
    return f"usage: {_invocation(node)}"


def composite_usage(node):
    lines = []
    for index, child in enumerate(node.children()):
        lead = "usage:" if index == 0 else "   or:"
        lines.append(f"{lead} {_invocation(child)}")
    lines.append("")
    lines.append(f"See '{program_name()} help {node.path} <command>' "
                 "for more information on a specific command.")
    return "\n".join(lines)


def command_help(node):
    sections = [("NAME", f"  {program_name()} {node.path}")]
    if node.description:
        sections.append(("DESCRIPTION", f"  {node.description}"))
    synopses = []
    if node.is_runnable():
        synopses.append(" ".join(
            w for w in (program_name(), node.path, node.synopsis.text()) if w))
    if node.has_children():
        synopses.append(f"{program_name()} {node.path} <command>")
    sections.append(("SYNOPSIS", "\n".join(f"  {s}" for s in synopses)))
    if node.alias:
        sections.append(("ALIAS", f"  {node.alias}"))
    defaults = node.defaults()
    if defaults:
        positional = set(node.synopsis.positional_names())
        sections.append(("DEFAULTS", "\n".join(
            f"  <{key}>: {value}" if key in positional else f"  --{key}: {value}"
            for key, value in defaults.items())))
    if node.has_children():
        sections.append(("SUBCOMMANDS", _columns(node.children())))
    return "\n\n".join(f"{title}\n\n{body}" for title, body in sections)
