"""Global parameter specification.

Secret: which global parameters exist, whether each may be given as a
runtime flag and/or in a config file, their defaults, runtime syntax, and
which are deprecated or hidden.
"""

from .synopsis import Synopsis


class Param:
    __slots__ = ("name", "runtime", "file", "default", "kind", "deprecated",
                 "hidden", "description")

    def __init__(self, name, *, runtime=None, file=True, default=None,
                 kind="value", deprecated=False, hidden=False, description=""):
        self.name = name
        self.runtime = runtime        # synopsis fragment, or None
        self.file = file
        self.default = default
        self.kind = kind              # "value", "list" or "bool"
        self.deprecated = deprecated
        self.hidden = hidden
        self.description = description


_PARAMS = [
    Param("path", runtime="[--path=<path>]",
          description="Path to the application files."),
    Param("url", runtime="[--url=<url>]",
          description="Pretend request came from given URL."),
    Param("user", runtime="[--user=<id>]",
          description="Set the user."),
    Param("ssh", runtime="[--ssh=<ssh>]",
          description="Perform operation against a remote server over SSH "
                      "(or a container using scheme of \"docker\", "
                      "\"docker-compose\", \"docker-compose-run\", \"vagrant\")."),
    Param("disabled_commands", default=[], kind="list",
          description="(Sub)commands to disable."),
    Param("projects_path", description="Directory in which projects are stored."),
    Param("locale", default="en_US", description="Locale to use."),
    Param("cert-email", description="E-mail address used for certificates."),
    Param("env", description="Environment name."),
    Param("admin-email", description="Administrator e-mail address."),
    Param("sysctl", description="Kernel parameters to apply."),
    Param("skip-tty", default=False, kind="bool",
          description="Do not allocate a TTY for remote commands."),
    Param("custom-compose", description="Custom compose file."),
    Param("installer_version", default="stable",
          description="Installer release channel."),
    Param("color", runtime="[--[no-]color]", default="auto",
          description="Whether to colorize the output."),
    Param("debug", runtime="[--debug[=<group>]]", file=False, default=False,
          description="Show all errors and add verbosity to bootstrap."),
    Param("quiet", runtime="[--quiet]", file=False, default=False,
          kind="bool", description="Suppress informational messages."),
]

_BY_NAME = {p.name: p for p in _PARAMS}


def params():
    return list(_PARAMS)


def get(name):
    return _BY_NAME.get(name)


def defaults():
    return {p.name: (list(p.default) if isinstance(p.default, list) else p.default)
            for p in _PARAMS}


def file_param(name):
    """The parameter named ``name`` if it may be set from a config file."""
    param = _BY_NAME.get(name)
    return param if param is not None and param.file else None


def runtime_synopsis():
    return Synopsis(" ".join(p.runtime for p in _PARAMS if p.runtime))


def is_deprecated(name):
    param = _BY_NAME.get(name)
    return bool(param and param.deprecated)


def visible():
    """Parameters that may be shown in help output."""
    return [p for p in _PARAMS if not p.hidden]
