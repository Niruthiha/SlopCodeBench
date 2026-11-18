"""Rendering of help text and usage lines."""

from . import PROGRAM_NAME
from .command import sort_key

INDENT = "  "


def command_line(command):
    """``appctl <path> <synopsis>`` for a runnable command."""
    parts = [PROGRAM_NAME] + command.path
    if command.synopsis:
        parts.append(command.synopsis)
    return " ".join(parts)


def composite_line(command):
    return " ".join([PROGRAM_NAME] + command.path + ["<command>"])


def usage_lines(command):
    """All invocation forms of a command, sorted by full command path."""
    lines = []
    if command.is_runnable:
        lines.append(command_line(command))
    for sub in command.sorted_subcommands():
        if sub.has_subcommands and not sub.is_runnable:
            lines.append(composite_line(sub))
        else:
            lines.append(command_line(sub))
    return lines


def render_usage(command):
    """The usage block printed when a command is invoked incorrectly."""
    if not command.has_subcommands:
        return f"usage: {command_line(command)}"
    lines = usage_lines(command)
    out = [f"usage: {lines[0]}"] + [f"   or: {line}" for line in lines[1:]]
    out.append("")
    out.append(
        f"See '{PROGRAM_NAME} help {command.full_name} <command>' "
        "for more information on a specific command."
    )
    return "\n".join(out)


def render_listing(commands):
    """Column-aligned ``name  description`` rows, alphabetically sorted."""
    commands = sorted(commands, key=lambda c: sort_key(c.name))
    if not commands:
        return []
    width = max(len(c.name) for c in commands)
    return [f"{INDENT}{c.name.ljust(width)}  {c.description}".rstrip() for c in commands]


def render_root_help(root):
    lines = [
        f"usage: {PROGRAM_NAME} <command> [<subcommand>] [<args>] [--<flags>]",
        "",
        "Available commands:",
        "",
    ]
    lines.extend(render_listing(root.subcommands.values()))
    lines.append("")
    lines.append(
        f"See '{PROGRAM_NAME} help <command>' for more information on a specific command."
    )
    return "\n".join(lines)


def _section(title, body_lines):
    return [title, ""] + body_lines + [""]


def _default_text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _option_lines(command):
    lines = []
    for token in command.tokens:
        lines.append(f"{INDENT}{token.token}")
        description = command.options.get(token.name) if token.name else None
        if description:
            lines.append(f"{INDENT * 2}{description}")
        if token.name and token.name in command.defaults:
            lines.append(f"{INDENT * 2}---")
            lines.append(f"{INDENT * 2}default: {_default_text(command.defaults[token.name])}")
            lines.append(f"{INDENT * 2}---")
        lines.append("")
    return lines[:-1]


def render_command_help(command):
    if command.is_root:
        return render_root_help(command)
    lines = []
    lines += _section("NAME", [f"{INDENT}{PROGRAM_NAME} {command.full_name}"])
    if command.description:
        lines += _section("DESCRIPTION", [f"{INDENT}{command.description}"])
    if command.longdesc:
        lines += [f"{INDENT}{line}".rstrip() for line in command.longdesc.splitlines()] + [""]
    synopsis = []
    if command.is_runnable:
        synopsis.append(f"{INDENT}{command_line(command)}")
    if command.has_subcommands:
        synopsis.append(f"{INDENT}{composite_line(command)}")
    lines += _section("SYNOPSIS", synopsis)
    if command.is_runnable and command.tokens:
        lines += _section("OPTIONS", _option_lines(command))
    if command.has_subcommands:
        lines += _section("SUBCOMMANDS", render_listing(command.subcommands.values()))
    if command.alias:
        lines += _section("ALIAS", [f"{INDENT}{command.alias}"])
    return "\n".join(lines).rstrip("\n")
