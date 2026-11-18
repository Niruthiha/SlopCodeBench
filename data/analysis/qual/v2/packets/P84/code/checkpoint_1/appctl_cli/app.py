"""Top-level orchestration: rewrite, parse, resolve, validate, run."""

import os
import sys

from .arguments import parse_argv
from .commands import build_command_tree
from .context import Context
from .errors import AppctlError, UsageError
from .help import render_root_help, render_usage
from .resolver import resolve
from .rewrites import apply_rewrites
from .runtime_config import build_runtime_config, is_strict_mode
from .validator import ArgumentValidator
from .output import Output


def main(argv=None, environ=None, stdout=None, stderr=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    environ = os.environ if environ is None else environ
    strict = is_strict_mode(environ)

    parsed = parse_argv(apply_rewrites(argv), strict=strict)
    runtime = build_runtime_config(parsed.runtime)
    output = Output(quiet=bool(runtime["quiet"]), debug=bool(runtime["debug"]),
                    stdout=stdout, stderr=stderr)
    root = build_command_tree()

    try:
        if not parsed.positional:
            output.line(render_root_help(root))
            return 0
        command, remaining = resolve(root, parsed.positional)
        if not command.is_runnable:
            output.line(render_usage(command))
            return 0
        output.debug(f"Running command: {command.full_name}")
        args, assoc = ArgumentValidator(command).validate(
            remaining, parsed.assoc, warn=output.warning
        )
        context = Context(root=root, command=command, output=output,
                          runtime=runtime, strict=strict)
        result = command.handler(context, args, assoc)
        return int(result or 0)
    except UsageError as exc:
        output.line(exc.usage)
        return exc.exit_code
    except AppctlError as exc:
        output.error(exc.message)
        return exc.exit_code
