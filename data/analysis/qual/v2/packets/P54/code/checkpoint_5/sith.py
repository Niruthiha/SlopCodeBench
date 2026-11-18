"""sith - static Python code completion and navigation.

Usage: python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
       python sith.py infer <file> <line> <col> [--project <dir>]
       python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
       python sith.py signatures <file> <line> <col> [--project <dir>]
       python sith.py references <file> <line> <col> [--scope file|project] [--project <dir>]
       python sith.py search <query> [--project <dir>]
       python sith.py names <file> [--all-scopes] [--project <dir>]
       python sith.py rename <file> <line> <col> --new-name <name> [--diff] [--project <dir>]
       python sith.py inline <file> <line> <col> [--diff] [--project <dir>]
       python sith.py extract-variable <file> <line> <col> --until <line>:<col> --name <name>
                      [--diff] [--project <dir>]
       python sith.py extract-function <file> <line> <col> --until <line>:<col> --name <name>
                      [--diff] [--project <dir>]
       python sith.py errors <file>
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sithlib import (diagnostics, engine, navigation, output, refactoring,  # noqa: E402
                     signatures, symbols)
from sithlib.source import SourceError  # noqa: E402

USAGE = ("usage: sith.py (complete|infer|goto|signatures|references|rename|inline|"
         "extract-variable|extract-function) <file> <line> <col> "
         "| search <query> | names <file> | errors <file> [--fuzzy] [--follow-imports] "
         "[--scope file|project] [--all-scopes] [--new-name <name>] [--name <name>] "
         "[--until <line>:<col>] [--diff] [--project <dir>]")
POSITION_COMMANDS = ("complete", navigation.INFER, navigation.GOTO, "signatures", "references")
REFACTORING_COMMANDS = ("rename", "inline", "extract-variable", "extract-function")
SCOPES = (symbols.FILE, symbols.PROJECT)
VALUED_OPTIONS = ("project", "scope", "new-name", "name", "until")


class Options:
    def __init__(self):
        self.fuzzy = False
        self.follow = False
        self.all_scopes = False
        self.scope = symbols.FILE
        self.project = None
        self.diff = False
        self.new_name = None
        self.name = None
        self.until = None


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
        elif arg == "--diff":
            options.diff = True
        elif arg[2:] in VALUED_OPTIONS and arg.startswith("--"):
            if index + 1 >= len(argv):
                return None
            index += 1
            setattr(options, arg[2:].replace("-", "_"), argv[index])
        elif arg.startswith("--") and arg[2:].split("=", 1)[0] in VALUED_OPTIONS:
            option, value = arg[2:].split("=", 1)
            setattr(options, option.replace("-", "_"), value)
        else:
            args.append(arg)
        index += 1
    if options.scope not in SCOPES:
        return None
    return args, options


def _refactor(command, path, line, col, options, project):
    try:
        if command == "rename":
            if options.new_name is None:
                return _fail("rename needs --new-name <name>")
            result = refactoring.rename(path, line, col, options.new_name, project)
        elif command == "inline":
            result = refactoring.inline(path, line, col, project)
        else:
            if options.name is None or options.until is None:
                return _fail("%s needs --until <line>:<col> and --name <name>" % command)
            try:
                until_line, until_col = (int(part) for part in options.until.split(":"))
            except ValueError:
                return _fail("--until must be <line>:<col>")
            extract = refactoring.extract_variable if command == "extract-variable" \
                else refactoring.extract_function
            result = extract(path, line, col, (until_line, until_col), options.name, project)
    except (SourceError, navigation.NotOnName, refactoring.RefactoringError) as exc:
        return _fail(str(exc))
    except Exception as exc:  # never emit a partial or unsafe edit
        return _fail("cannot %s here (%s)" % (command, exc))
    if options.diff:
        output.write_text(result.diff())
    else:
        output.write_changes(result.changed_files(), result.renamed_paths())
    return 0


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
    if len(args) == 2 and args[0] == "errors":
        try:
            found = diagnostics.errors(args[1])
        except SourceError as exc:
            return _fail(str(exc))
        output.write_errors(found)
        return 0
    if len(args) != 4 or args[0] not in POSITION_COMMANDS + REFACTORING_COMMANDS:
        return _fail(USAGE)
    try:
        line, col = int(args[2]), int(args[3])
    except ValueError:
        return _fail("line and column must be integers")
    command, path = args[0], args[1]
    if command in REFACTORING_COMMANDS:
        return _refactor(command, path, line, col, options, project)
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
