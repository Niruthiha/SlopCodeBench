"""Command-line interface: argument parsing, JSON output and exit codes."""
import argparse
import contextlib
import io
import json
import sys

from .completion import complete_file
from .errors import SithError
from .listing import list_names, search_project
from .navigation import GOTO, INFER, navigate
from .references import FILE, PROJECT, find_references
from .signatures import signatures_at

# The JSON key(s) holding each command's results.
_RESULT_KEYS = {
    "complete": ("completions",),
    INFER: ("definitions",),
    GOTO: ("definitions",),
    "signatures": ("signatures",),
    "references": ("references",),
    "search": ("definitions", "results"),
    "names": ("names", "definitions"),
    "errors": ("errors",),
}
# Commands that compute a refactoring (JSON `changed_files`/`renames`, or a diff).
_REFACTORINGS = ("rename", "inline", "extract-variable", "extract-function")


class _ArgumentParser(argparse.ArgumentParser):
    """An ArgumentParser that reports usage errors as SithError (exit 1)."""

    def error(self, message):
        raise SithError(message)


def _add_project_argument(parser, default="the directory containing the file"):
    parser.add_argument("--project", default=None, help=f"project root (default: {default})")


def _add_position_arguments(parser):
    parser.add_argument("file", help="Python source file")
    parser.add_argument("line", type=int, help="1-based line number")
    parser.add_argument("col", type=int, help="0-based column number")
    _add_project_argument(parser)


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
    goto.add_argument("--follow-imports", action="store_true",
                      help="follow imports to the definitions they import")
    signatures = commands.add_parser("signatures", help="signatures of the call at a cursor position")
    _add_position_arguments(signatures)
    references = commands.add_parser("references",
                                     help="find the references to the name at a cursor position")
    _add_position_arguments(references)
    references.add_argument("--scope", choices=(FILE, PROJECT), default=FILE,
                            help="search the file only (default) or the whole project")
    search = commands.add_parser("search", help="search the project for definitions by name")
    search.add_argument("query", help="case-insensitive substring of the names to find")
    _add_project_argument(search, default="the current directory")
    names = commands.add_parser("names", help="list the names defined in a file")
    names.add_argument("file", help="Python source file")
    names.add_argument("--all-scopes", action="store_true",
                       help="include names defined in nested scopes")
    _add_project_argument(names)
    errors = commands.add_parser("errors", help="report the syntax errors of a file")
    errors.add_argument("file", help="Python source file")
    rename = commands.add_parser("rename", help="rename the name at a cursor position")
    _add_position_arguments(rename)
    rename.add_argument("--new-name", required=True, help="the new name")
    inline = commands.add_parser("inline", help="inline the variable at a cursor position")
    _add_position_arguments(inline)
    for command in ("extract-variable", "extract-function"):
        extract = commands.add_parser(command, help=f"{command.replace('-', ' ')} from a selection")
        _add_position_arguments(extract)
        extract.add_argument("--until", required=True, type=_position,
                             help="end of the selection, as LINE:COL")
        extract.add_argument("--name", required=True, help="name of the new "
                             + command.split("-")[1])
    for command in _REFACTORINGS:
        commands.choices[command].add_argument("--diff", action="store_true",
                                               help="output a unified diff instead of JSON")
    return parser


def _position(text):
    line, separator, col = text.partition(":")
    try:
        if separator:
            return int(line), int(col)
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(f"invalid position {text!r} (expected LINE:COL)")


def _refactor(args):
    command = args.command
    if command == "rename":
        from .rename import rename
        return rename(args.file, args.line, args.col, args.new_name, project=args.project)
    if command == "inline":
        from .inline import inline
        return inline(args.file, args.line, args.col, project=args.project)
    from .extract import extract_function, extract_variable
    function = extract_variable if command == "extract-variable" else extract_function
    return function(args.file, (args.line, args.col), args.until, args.name,
                    project=args.project)


def _main_refactoring(args):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            refactoring = _refactor(args)
    except SithError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # never emit a partial or unsafe edit
        print(f"error: refactoring failed: {error!r}", file=sys.stderr)
        return 1
    if args.diff:
        sys.stdout.write(refactoring.to_diff())
    else:
        sys.stdout.write(json.dumps(refactoring.to_dict(), separators=(",", ":")) + "\n")
    return 0


def _run(args):
    command = args.command
    if command == "complete":
        results = complete_file(args.file, args.line, args.col, fuzzy=args.fuzzy,
                                project=args.project)
    elif command == "signatures":
        results = signatures_at(args.file, args.line, args.col, project=args.project)
    elif command == "references":
        results = find_references(args.file, args.line, args.col, scope=args.scope,
                                  project=args.project)
    elif command == "search":
        return search_project(args.query, project=args.project)
    elif command == "names":
        return list_names(args.file, all_scopes=args.all_scopes, project=args.project)
    elif command == "errors":
        from .syntax_errors import syntax_errors
        results = syntax_errors(args.file)
    else:
        results = navigate(command, args.file, args.line, args.col, project=args.project,
                           follow_imports=getattr(args, "follow_imports", False))
    return [result.to_dict() for result in results]


def main(argv=None):
    keys = _RESULT_KEYS["complete"]
    try:
        args = build_parser().parse_args(argv)
        if args.command in _REFACTORINGS:
            return _main_refactoring(args)
        keys = _RESULT_KEYS[args.command]
        # Introspected modules may print; keep STDOUT reserved for the JSON result.
        with contextlib.redirect_stdout(io.StringIO()):
            results = _run(args)
    except SithError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # analysis must never crash an editor integration
        print(f"warning: analysis failed: {error!r}", file=sys.stderr)
        results = []
    payload = {key: results for key in keys}
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return 0
