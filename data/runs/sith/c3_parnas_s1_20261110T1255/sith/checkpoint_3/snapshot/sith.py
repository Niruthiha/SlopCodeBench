"""sith - static Python code completion and navigation.

Usage: python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
       python sith.py infer <file> <line> <col> [--project <dir>]
       python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sithlib import engine, navigation, output  # noqa: E402
from sithlib.source import SourceError  # noqa: E402

USAGE = ("usage: sith.py (complete|infer|goto) <file> <line> <col> [--fuzzy] "
         "[--follow-imports] [--project <dir>]")
COMMANDS = ("complete", navigation.INFER, navigation.GOTO)


def _fail(message):
    sys.stderr.write("error: %s\n" % message)
    return 1


def _parse(argv):
    """Return (positional args, fuzzy, follow imports, project dir) or None if malformed."""
    fuzzy = False
    follow = False
    project = None
    args = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--fuzzy":
            fuzzy = True
        elif arg == "--follow-imports":
            follow = True
        elif arg == "--project":
            if index + 1 >= len(argv):
                return None
            index += 1
            project = argv[index]
        elif arg.startswith("--project="):
            project = arg[len("--project="):]
        else:
            args.append(arg)
        index += 1
    return args, fuzzy, follow, project


def main(argv):
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
    parsed = _parse(argv)
    if parsed is None:
        return _fail(USAGE)
    args, fuzzy, follow, project = parsed
    if len(args) != 4 or args[0] not in COMMANDS:
        return _fail(USAGE)
    try:
        line, col = int(args[2]), int(args[3])
    except ValueError:
        return _fail("line and column must be integers")
    if project is not None and not os.path.isdir(project):
        project = None
    command, path = args[0], args[1]
    if command == "complete":
        try:
            completions = engine.complete(path, line, col, fuzzy, project)
        except SourceError as exc:
            return _fail(str(exc))
        except Exception:  # analysis must never crash on odd input; degrade to nothing
            completions = []
        output.write_completions(completions)
        return 0
    try:
        definitions = navigation.run(command, path, line, col, project,
                                     follow_imports=follow and command == navigation.GOTO)
    except (SourceError, navigation.NotOnName) as exc:
        return _fail(str(exc))
    except Exception:  # analysis must never crash on odd input; degrade to nothing
        definitions = []
    output.write_definitions(definitions)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
