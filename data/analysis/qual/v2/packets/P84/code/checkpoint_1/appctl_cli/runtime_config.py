"""Global runtime configuration parameters."""

from dataclasses import dataclass

STRICT_ARGS_ENV = "APPCTL_STRICT_ARGS_MODE"


@dataclass(frozen=True)
class GlobalParameter:
    name: str
    synopsis: str
    description: str
    default: object = None


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
        GlobalParameter("color", "--[no-]color", "Whether to colorize the output.", "auto"),
        GlobalParameter("debug", "--debug[=<group>]", "Show all errors and debug messages.", False),
        GlobalParameter("prompt", "--prompt[=<assoc>]", "Prompt the user to enter values for all arguments.", False),
        GlobalParameter("quiet", "--quiet", "Suppress informational messages.", False),
    )
}


def is_global_parameter(key):
    return key in GLOBAL_PARAMETERS


def is_strict_mode(environ):
    return bool(environ.get(STRICT_ARGS_ENV))


def build_runtime_config(supplied):
    """Merge supplied global values over the defaults."""
    config = {name: param.default for name, param in GLOBAL_PARAMETERS.items()}
    config.update(supplied)
    return config
