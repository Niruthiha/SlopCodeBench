"""``appctl cli``: information about appctl itself."""

import json
import platform

from .. import PROGRAM_NAME, __version__
from ..formatter import format_value
from ..errors import AppctlError
from ..resolver import try_resolve
from ..runtime_config import GLOBAL_PARAMETERS, visible_parameters


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
        ctx.output.line(json.dumps(data))
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
        "cli param-dump", param_dump,
        synopsis="[--with-values] [--format=<format>]",
        description="Dumps the list of global parameters, as JSON.",
        defaults={"format": "json"},
        options={"with-values": "Display current values also."},
    )
    registry.add(
        "cli has-command", has_command,
        synopsis="<command-name>...",
        description="Detects if a command exists.",
        options={"command-name": "The command to check."},
    )
