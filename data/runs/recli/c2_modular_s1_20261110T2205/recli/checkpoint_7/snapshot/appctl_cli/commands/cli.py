"""``appctl cli``: information about appctl itself."""

import os
import platform

from .. import PROGRAM_NAME, __version__, upgrade
from ..arguments import is_assoc_token, parse_assoc_token
from ..formatter import format_value
from ..errors import AppctlError
from ..extract import extract_archive, validate_archive
from ..resolver import try_resolve
from ..runtime_config import GLOBAL_PARAMETERS, visible_parameters
from ..synopsis import ASSOC, FLAG


def version(ctx, args, assoc):
    ctx.output.line(f"{PROGRAM_NAME} {__version__}")


def info(ctx, args, assoc):
    data = {
        "appctl_version": __version__,
        "python_version": platform.python_version(),
        "os": platform.system(),
        "strict_args_mode": ctx.strict,
        "global_config_path": ctx.config.global_path if ctx.config else None,
        "project_config_path": ctx.config.project_path if ctx.config else None,
        "packages_dir": ctx.config.packages_dir if ctx.config else None,
        "runtime_config": {k: v for k, v in ctx.runtime.items()
                           if v != GLOBAL_PARAMETERS[k].default},
    }
    if assoc["format"] == "json":
        ctx.output.line(format_value(data, "json"))
        return
    if assoc["format"] != "list":
        raise AppctlError(f"Invalid format: {assoc['format']}. Supported formats: list, json.")
    ctx.output.line(f"appctl version:\t{data['appctl_version']}")
    ctx.output.line(f"Python version:\t{data['python_version']}")
    ctx.output.line(f"OS:\t{data['os']}")
    ctx.output.line(f"Strict args mode:\t{'enabled' if ctx.strict else 'disabled'}")
    ctx.output.line(f"Global config:\t{data['global_config_path'] or ''}")
    ctx.output.line(f"Project config:\t{data['project_config_path'] or ''}")
    ctx.output.line(f"Packages dir:\t{data['packages_dir'] or ''}")
    for key, value in data["runtime_config"].items():
        ctx.output.line(f"--{key}:\t{format_value(value)}")


def update(ctx, args, assoc):
    archive = assoc.get("archive")
    validate_archive(archive)
    dest = assoc.get("path") or ctx.runtime.get("path") or os.getcwd()
    if dest is True:
        raise AppctlError("--path parameter needs a value.")
    dest = extract_archive(archive, str(dest), ctx.output)
    ctx.output.success(f"Extracted '{archive}' to '{dest}'.")


def migrate(ctx, args, assoc):
    upgrade.run_upgrade(ctx.environ, ctx.output)
    ctx.output.success(f"Upgraded to {PROGRAM_NAME} {__version__}.")


def param_dump(ctx, args, assoc):
    dump = {}
    for name, param in visible_parameters().items():
        entry = {"synopsis": param.synopsis, "description": param.description,
                 "default": param.default}
        if assoc.get("with-values"):
            entry["current"] = ctx.runtime.get(name)
        dump[name] = entry
    ctx.output.line(format_value(dump, "json"))


def has_command(ctx, args, assoc):
    tokens = " ".join(args).split()
    resolved = try_resolve(ctx.root, tokens)
    found = resolved is not None and not resolved[1]
    return 0 if found else 1


def _completion_words(line):
    """Split the line into completed words and the word being typed."""
    words = line.split()
    current = words.pop() if words and not line[-1].isspace() else ""
    if words and os.path.basename(words[0]) in (PROGRAM_NAME, f"{PROGRAM_NAME}.py"):
        words = words[1:]
    elif not words and os.path.basename(current) in (PROGRAM_NAME, f"{PROGRAM_NAME}.py"):
        current = ""
    return words, current


def completion_candidates(root, line):
    words, current = _completion_words(line)
    used = {parse_assoc_token(w)[0] for w in words if is_assoc_token(w)}
    command = root
    consumed = True
    for word in (w for w in words if not is_assoc_token(w)):
        child = command.find_subcommand(word) if consumed else None
        if child is None:
            if not command.is_runnable or command.is_root:
                return []
            consumed = False
            continue
        command = child
    candidates = []
    if consumed:
        candidates += [f"{sub.name} " for sub in command.sorted_subcommands()]
    if command.is_runnable and not command.is_root:
        for token in command.tokens_of_type(ASSOC, FLAG):
            if token.name not in used:
                candidates.append(f"--{token.name}=" if token.type == ASSOC else f"--{token.name} ")
        for name, param in visible_parameters().items():
            if param.runtime and name not in used:
                candidates.append(f"--{name}=" if "=" in param.synopsis else f"--{name} ")
    return [c for c in candidates if c.startswith(current)]


def completions(ctx, args, assoc):
    line = str(assoc["line"])
    point = assoc.get("point")
    if point is not None and point is not True:
        try:
            line = line[:int(point)]
        except ValueError:
            pass
    for candidate in completion_candidates(ctx.root, line):
        ctx.output.line(candidate)


def register(registry):
    registry.add("cli", description="Reviews current appctl info.")
    registry.add("cli version", version, description="Prints the appctl version.")
    registry.add(
        "cli info", info,
        synopsis="[--format=<format>]",
        description="Prints various details about the appctl environment.",
        defaults={"format": "list"},
        options={"format": "Render output in a particular format (list, json)."},
    )
    registry.add(
        "cli update", update,
        synopsis="--archive=<archive-path> [--path=<destination>]",
        description="Extracts a .zip or .tar.gz archive into a directory.",
        options={"archive": "Path to the archive to extract.",
                 "path": "Directory to extract into. Defaults to the current directory."},
    )
    registry.add(
        "cli migrate", migrate,
        description="Runs pending migrations and upgrades containers to the current version.",
    )
    registry.add(
        "cli param-dump", param_dump,
        synopsis="[--with-values] [--format=<format>]",
        description="Dumps the list of global parameters, as JSON.",
        defaults={"format": "json"},
        options={"with-values": "Display current values also."},
    )
    registry.add(
        "cli completions", completions,
        synopsis="--line=<line> [--point=<point>]",
        description="Generates tab completion strings.",
        options={"line": "The current command line to be executed.",
                 "point": "The index to the current cursor position relative to the beginning "
                          "of the command."},
    )
    registry.add(
        "cli has-command", has_command,
        synopsis="<command-name>...",
        description="Detects if a command exists.",
        options={"command-name": "The command to check."},
    )
