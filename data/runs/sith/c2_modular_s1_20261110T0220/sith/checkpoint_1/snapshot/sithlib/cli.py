"""Command-line interface: argument parsing, JSON output and exit codes."""
import argparse
import contextlib
import io
import json
import sys

from .completion import complete_file
from .errors import SithError


class _ArgumentParser(argparse.ArgumentParser):
    """An ArgumentParser that reports usage errors as SithError (exit 1)."""

    def error(self, message):
        raise SithError(message)


def build_parser():
    parser = _ArgumentParser(prog="sith.py", description="Python code intelligence.")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_ArgumentParser)
    complete = commands.add_parser("complete", help="complete the code at a cursor position")
    complete.add_argument("file", help="Python source file")
    complete.add_argument("line", type=int, help="1-based line number")
    complete.add_argument("col", type=int, help="0-based column number")
    complete.add_argument("--fuzzy", action="store_true", help="use fuzzy matching")
    return parser


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
        # Introspected modules may print; keep STDOUT reserved for the JSON result.
        with contextlib.redirect_stdout(io.StringIO()):
            completions = complete_file(args.file, args.line, args.col, fuzzy=args.fuzzy)
    except SithError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # analysis must never crash an editor integration
        print(f"warning: analysis failed: {error!r}", file=sys.stderr)
        completions = []
    payload = {"completions": [c.to_dict() for c in completions]}
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return 0
