"""sith - static Python code completion and navigation.

Usage: python sith.py complete <file> <line> <col> [--fuzzy] [--project <dir>]
       python sith.py infer <file> <line> <col> [--project <dir>]
       python sith.py goto <file> <line> <col> [--follow-imports] [--project <dir>]
       python sith.py signatures <file> <line> <col> [--project <dir>]
           (these four also take [--interpreter [--namespaces <file>]])
       python sith.py context <file> <line> <col> [--project <dir>]
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
       python sith.py env list
       python sith.py env find-virtualenvs [--path <dir>]
       python sith.py env info [<executable>]
       python sith.py project init [<dir>] [--environment <executable>]
                      [--sys-path <path>[,<path>...]] [--added-sys-path <path>[,<path>...]]

Every command takes [--setting key=value]... (case_insensitive, dynamic_params,
smart_sys_path, add_bracket); they override the project's .sith/project.json.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sithlib import (config, diagnostics, enclosing, engine, environments,  # noqa: E402
                     interpreter, navigation, output, refactoring, signatures, symbols)
from sithlib.source import SourceError  # noqa: E402

USAGE = ("usage: sith.py (complete|infer|goto|signatures|context|references|rename|inline|"
         "extract-variable|extract-function) <file> <line> <col> "
         "| search <query> | names <file> | errors <file> "
         "| env (list|find-virtualenvs|info [<executable>]) | project init [<dir>] "
         "[--fuzzy] [--follow-imports] "
         "[--scope file|project] [--all-scopes] [--new-name <name>] [--name <name>] "
         "[--until <line>:<col>] [--diff] [--project <dir>] [--interpreter] "
         "[--namespaces <file>] [--setting key=value] [--path <dir>] "
         "[--environment <executable>] [--sys-path <paths>] [--added-sys-path <paths>]")
POSITION_COMMANDS = ("complete", navigation.INFER, navigation.GOTO, "signatures", "references",
                     "context")
INTERPRETER_COMMANDS = ("complete", navigation.INFER, navigation.GOTO, "signatures")
REFACTORING_COMMANDS = ("rename", "inline", "extract-variable", "extract-function")
SCOPES = (symbols.FILE, symbols.PROJECT)
VALUED_OPTIONS = ("project", "scope", "new-name", "name", "until", "namespaces", "path",
                  "environment", "sys-path", "added-sys-path")


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
        self.interpreter = False
        self.namespaces = None
        self.settings = []
        self.path = None
        self.environment = None
        self.sys_path = None
        self.added_sys_path = None


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
        elif arg == "--interpreter":
            options.interpreter = True
        elif arg == "--setting":
            if index + 1 >= len(argv):
                return None
            index += 1
            options.settings.append(argv[index])
        elif arg.startswith("--setting="):
            options.settings.append(arg[len("--setting="):])
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


def _env(args, options, overrides):
    if args == ["env", "list"]:
        output.write_environments(e.summary() for e in environments.system_environments())
        return 0
    if args == ["env", "find-virtualenvs"]:
        if options.path is not None and not os.path.isdir(options.path):
            return _fail("not a directory: %s" % options.path)
        root = options.project if options.project and os.path.isdir(options.project) else None
        found = environments.virtualenvs(options.path, root)
        output.write_environments(e.summary() for e in found)
        return 0
    if len(args) in (2, 3) and args[1] == "info":
        if len(args) == 3:
            executable = environments.find_executable(args[2])
        else:
            root = options.project if options.project and os.path.isdir(options.project) \
                else os.getcwd()
            configured = config.resolve(root, overrides).environment_path
            executable = environments.find_executable(configured) if configured \
                else environments.default_executable()
        found = environments.probe(executable) if executable else None
        if found is None:
            return _fail("not a usable Python executable: %s"
                         % (args[2] if len(args) == 3 else executable or "python3"))
        output.write_environment(found.details())
        return 0
    return _fail(USAGE)


def _project_init(args, options, overrides):
    if len(args) > 3:
        return _fail(USAGE)
    directory = os.path.abspath(args[2] if len(args) == 3 else os.getcwd())
    if os.path.exists(directory) and not os.path.isdir(directory):
        return _fail("not a directory: %s" % directory)
    updates = {}
    if options.environment is not None:
        updates["environment_path"] = options.environment
    if options.sys_path is not None:
        updates["sys_path"] = config.split_paths(options.sys_path)
    if options.added_sys_path is not None:
        updates["added_sys_path"] = config.split_paths(options.added_sys_path)
    if "smart_sys_path" in overrides:
        updates["smart_sys_path"] = overrides["smart_sys_path"]
    try:
        _, configuration = config.init_project(directory, updates)
    except config.ConfigError as exc:
        return _fail(str(exc))
    output.write_configuration(configuration)
    return 0


def main(argv):
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
    parsed = _parse(argv)
    if parsed is None:
        return _fail(USAGE)
    args, options = parsed
    overrides = {}
    try:
        for setting in options.settings:
            key, value = config.parse_setting(setting)
            overrides[key] = value
    except config.ConfigError as exc:
        return _fail(str(exc))
    if options.namespaces is not None and not options.interpreter:
        return _fail("--namespaces requires --interpreter")
    if args and args[0] == "env":
        return _env(args, options, overrides)
    if args[:2] == ["project", "init"]:
        return _project_init(args, options, overrides)
    project = options.project
    if project is not None and not os.path.isdir(project):
        project = None
    if project is not None:
        root = project
    elif len(args) >= 2 and args[0] != "search":
        root = os.path.dirname(os.path.abspath(args[1]))
    else:
        root = os.getcwd()
    config.activate(config.resolve(root, overrides))
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
    if command == "context":
        try:
            found = enclosing.context(path, line, col)
        except SourceError as exc:
            return _fail(str(exc))
        except Exception:  # analysis must never crash on odd input; degrade to nothing
            found = []
        output.write_context(found)
        return 0
    namespaces = None
    if options.interpreter and options.namespaces is not None \
            and command in INTERPRETER_COMMANDS:
        try:
            namespaces = interpreter.load(options.namespaces)
        except interpreter.NamespaceError as exc:
            return _fail(str(exc))
    if command == "complete":
        try:
            completions = engine.complete(path, line, col, options.fuzzy, project, namespaces)
        except SourceError as exc:
            return _fail(str(exc))
        except Exception:  # analysis must never crash on odd input; degrade to nothing
            completions = []
        output.write_completions(completions)
        return 0
    if command == "signatures":
        try:
            found = signatures.signatures(path, line, col, project, namespaces)
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
                                     follow_imports=options.follow and command == navigation.GOTO,
                                     namespaces=namespaces)
    except (SourceError, navigation.NotOnName) as exc:
        return _fail(str(exc))
    except Exception:  # analysis must never crash on odd input; degrade to nothing
        definitions = []
    output.write_definitions(definitions)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
