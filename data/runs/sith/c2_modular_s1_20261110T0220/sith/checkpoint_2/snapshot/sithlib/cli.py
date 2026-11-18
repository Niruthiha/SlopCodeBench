"""Command-line interface: argument parsing, JSON output and exit codes."""
import argparse
import contextlib
import io
import json
import sys

from .completion import complete_file
from .errors import SithError
from .navigation import GOTO, INFER, navigate


class _ArgumentParser(argparse.ArgumentParser):
    """An ArgumentParser that reports usage errors as SithError (exit 1)."""

    def error(self, message):
        raise SithError(message)


def _add_position_arguments(parser):
    parser.add_argument("file", help="Python source file")
    parser.add_argument("line", type=int, help="1-based line number")
    parser.add_argument("col", type=int, help="0-based column number")
    parser.add_argument("--project", default=None,
                        help="project root (default: the directory containing the file)")


def build_parser():
    parser = _ArgumentParser(prog="sith.py", description="Python code intelligence.")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_ArgumentParser)
    complete = commands.add_parser("complete", help="complete the code at a cursor position")
    _add_position_arguments(complete)
    complete.add_argument("--fuzzy", action="store_true", help="use fuzzy matching")
    infer = commands.add_parser(INFER, help="infer what the name at a cursor position evaluates to")
    _add_position_arguments(infer)
    goto = commands.add_parser(GOTO, help="find where the name at a cursor position is defined")
    _add_position_arguments(goto)
    return parser


def _run(args):
    if args.command == "complete":
        completions = complete_file(args.file, args.line, args.col, fuzzy=args.fuzzy,
                                    project=args.project)
        return "completions", [c.to_dict() for c in completions]
    definitions = navigate(args.command, args.file, args.line, args.col, project=args.project)
    return "definitions", [d.to_dict() for d in definitions]


def main(argv=None):
    key = "completions"
    try:
        args = build_parser().parse_args(argv)
        key = "completions" if args.command == "complete" else "definitions"
        # Introspected modules may print; keep STDOUT reserved for the JSON result.
        with contextlib.redirect_stdout(io.StringIO()):
            key, results = _run(args)
    except SithError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # analysis must never crash an editor integration
        print(f"warning: analysis failed: {error!r}", file=sys.stderr)
        results = []
    payload = {key: results}
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return 0
