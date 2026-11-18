"""``appctl help``: show help for any command."""

from ..help import render_command_help, render_root_help
from ..resolver import resolve


def help_command(ctx, args, assoc):
    if not args:
        ctx.output.line(render_root_help(ctx.root))
        return
    command, _ = resolve(ctx.root, args)
    ctx.output.line(render_command_help(command))


def register(registry):
    registry.add(
        "help", help_command,
        synopsis="[<command>...]",
        description="Gets help for appctl commands.",
        options={"command": "Get help on a specific command."},
    )
