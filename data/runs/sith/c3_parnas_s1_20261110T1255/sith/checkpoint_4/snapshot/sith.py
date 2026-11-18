"""sith - static Python code completion and navigation.

Usage: python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
       python sith.py infer <file> <line> <col> [--project <dir>]
       python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
       python sith.py signatures <file> <line> <col> [--project <dir>]
       python sith.py references <file> <line> <col> [--scope file|project] [--project <dir>]
       python sith.py search <query> [--project <dir>]
       python sith.py names <file> [--all-scopes] [--project <dir>]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sithlib import engine, navigation, output, signatures, symbols  # noqa: E402
from sithlib.source import SourceError  # noqa: E402

USAGE = ("usage: sith.py (complete|infer|goto|signatures|references) <file> <line> <col> "
         "| search <query> | names <file> [--fuzzy] [--follow-imports] "
         "[--scope file|project] [--all-scopes] [--project <dir>]")
POSITION_COMMANDS = ("complete", navigation.INFER, navigation.GOTO, "signatures", "references")
SCOPES = (symbols.FILE, symbols.PROJECT)


class Options:
    def __init__(self):
        self.fuzzy = False
        self.follow = False
        self.all_scopes = False
        self.scope = symbols.FILE
        self.project = None


def _fail(message):
    sys.stderr.write("error: %s\n" % message)
    return 1


def _parse(argv):
    """Return (positional args, Options) or None if malformed."""
    options = Options()
    args = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--fuzzy":
            options.fuzzy = True
        elif arg == "--follow-imports":
            options.follow = True
        elif arg == "--all-scopes":
            options.all_scopes = True
        elif arg in ("--project", "--scope"):
            if index + 1 >= len(argv):
                return None
            index += 1
            setattr(options, arg[2:], argv[index])
        elif arg.startswith("--project="):
            options.project = arg[len("--project="):]
        elif arg.startswith("--scope="):
            options.scope = arg[len("--scope="):]
        else:
            args.append(arg)
        index += 1
    if options.scope not in SCOPES:
        return None
    return args, options


def main(argv):
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
    parsed = _parse(argv)
    if parsed is None:
        return _fail(USAGE)
    args, options = parsed
    project = options.project
    if project is not None and not os.path.isdir(project):
        project = None
    if len(args) == 2 and args[0] == "search":
        try:
            found = symbols.search(args[1], project)
        except Exception:  # analysis must never crash on odd input; degrade to nothing
            found = []
        output.write_search_results(found)
        return 0
    if len(args) == 2 and args[0] == "names":
        try:
            found = symbols.names(args[1], options.all_scopes, project)
        except SourceError as exc:
            return _fail(str(exc))
        except Exception:  # analysis must never crash on odd input; degrade to nothing
            found = []
        output.write_names(found)
        return 0
    if len(args) != 4 or args[0] not in POSITION_COMMANDS:
        return _fail(USAGE)
    try:
        line, col = int(args[2]), int(args[3])
    except ValueError:
        return _fail("line and column must be integers")
    command, path = args[0], args[1]
    if command == "complete":
        try:
            completions = engine.complete(path, line, col, options.fuzzy, project)
        except SourceError as exc:
            return _fail(str(exc))
        except Exception:  # analysis must never crash on odd input; degrade to nothing
            completions = []
        output.write_completions(completions)
        return 0
    if command == "signatures":
        try:
            found = signatures.signatures(path, line, col, project)
        except SourceError as exc:
            return _fail(str(exc))
        except Exception:  # analysis must never crash on odd input; degrade to nothing
            found = []
        output.write_signatures(found)
        return 0
    if command == "references":
        try:
            found = symbols.references(path, line, col, options.scope, project)
        except (SourceError, navigation.NotOnName) as exc:
            return _fail(str(exc))
        except Exception:  # analysis must never crash on odd input; degrade to nothing
            found = []
        output.write_references(found)
        return 0
    try:
        definitions = navigation.run(command, path, line, col, project,
                                     follow_imports=options.follow and command == navigation.GOTO)
    except (SourceError, navigation.NotOnName) as exc:
        return _fail(str(exc))
    except Exception:  # analysis must never crash on odd input; degrade to nothing
        definitions = []
    output.write_definitions(definitions)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
