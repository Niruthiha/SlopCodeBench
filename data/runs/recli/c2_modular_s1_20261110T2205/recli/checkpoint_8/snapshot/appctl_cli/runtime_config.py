"""Global runtime configuration parameters."""

import copy
from dataclasses import dataclass

STRICT_ARGS_ENV = "APPCTL_STRICT_ARGS_MODE"


@dataclass(frozen=True)
class GlobalParameter:
    name: str
    synopsis: str
    description: str
    default: object = None
    runtime: bool = True
    file: bool = True
    multiple: bool = False
    deprecated: str = None
    hidden: bool = False


def _file_only(name, description, default=None):
    return GlobalParameter(name, "", description, default, runtime=False, file=True)


GLOBAL_PARAMETERS = {
    p.name: p
    for p in (
        GlobalParameter("path", "--path=<path>", "Path to the application files.", None),
        GlobalParameter("url", "--url=<url>", "Pretend request came from given URL.", None),
        GlobalParameter("ssh", "--ssh=<[scheme:][user@]host|container>[:port][path]",
                        "Perform operation against a remote server over SSH.", None),
        GlobalParameter("http", "--http=<http>", "Perform operation against a remote install over HTTP.", None),
        GlobalParameter("user", "--user=<id|login|email>", "Set the user for the current request.", None),
        GlobalParameter("skip-plugins", "--skip-plugins[=<plugins>]", "Skip loading all or some plugins.", False),
        GlobalParameter("skip-themes", "--skip-themes[=<themes>]", "Skip loading all or some themes.", False),
        GlobalParameter("skip-packages", "--skip-packages", "Skip loading all installed packages.", False),
        GlobalParameter("require", "--require=<path>", "Load a file before running the command.", None),
        GlobalParameter("exec", "--exec=<php-code>", "Execute code before running the command.", None),
        GlobalParameter("context", "--context=<context>", "Load the application in a given context.", "cli"),
        _file_only("disabled_commands", "(Sub)commands to disable.", []),
        _file_only("projects_path", "Path where projects are stored."),
        _file_only("locale", "Locale to use.", "en_US"),
        _file_only("cert-email", "Email address used for certificate registration."),
        _file_only("env", "Environment the tool runs in."),
        _file_only("admin-email", "Email address of the administrator."),
        _file_only("sysctl", "Kernel parameters applied to containers."),
        _file_only("skip-tty", "Never allocate a TTY for remote commands.", False),
        _file_only("custom-compose", "Path to a custom compose file."),
        _file_only("installer_version", "Release channel of the installer.", "stable"),
        GlobalParameter("color", "--[no-]color", "Whether to colorize the output.", "auto"),
        GlobalParameter("debug", "--debug[=<group>]", "Show all errors and debug messages.", False,
                        file=False),
        GlobalParameter("prompt", "--prompt[=<assoc>]", "Prompt the user to enter values for all arguments.",
                        False, file=False),
        GlobalParameter("quiet", "--quiet", "Suppress informational messages.", False, file=False),
    )
}


def is_global_parameter(key):
    """True for global parameters that may be given as runtime flags."""
    param = GLOBAL_PARAMETERS.get(key)
    return param is not None and param.runtime


def is_file_parameter(key):
    param = GLOBAL_PARAMETERS.get(key)
    return param is not None and param.file


def visible_parameters():
    """Global parameters that may be shown in help output."""
    return {name: p for name, p in GLOBAL_PARAMETERS.items() if not p.hidden}


def deprecation_warnings(supplied):
    """Warning lines for every deprecated parameter used as a runtime flag."""
    return [
        f"Warning: The --{key} global parameter is deprecated."
        for key in supplied
        if key in GLOBAL_PARAMETERS and GLOBAL_PARAMETERS[key].deprecated is not None
    ]


def is_strict_mode(environ):
    return bool(environ.get(STRICT_ARGS_ENV))


def _arrayify(value):
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def build_runtime_config(supplied, *layers):
    """Merge configuration over the defaults.

    ``layers`` are file-derived mappings from lowest to highest precedence
    (e.g. global config, project config, alias); only recognized
    file parameters are taken from them. ``supplied`` holds the runtime
    flags, which win over everything.
    """
    config = {name: copy.deepcopy(param.default) for name, param in GLOBAL_PARAMETERS.items()}
    for layer in layers:
        for key, value in (layer or {}).items():
            if is_file_parameter(key):
                config[key] = value
    config.update(supplied)
    config["disabled_commands"] = [str(c) for c in _arrayify(config.get("disabled_commands"))]
    return config
