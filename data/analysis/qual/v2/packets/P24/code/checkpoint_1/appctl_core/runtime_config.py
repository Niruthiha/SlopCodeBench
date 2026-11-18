"""Global runtime parameters.

Secret: which global parameters exist, which environment variable enables
strict arguments mode, and which argv positions may supply global
parameters in each mode.
"""

from . import messages as _messages
from .errors import CliError
from .synopsis import Synopsis

_STRICT_ENV = "APPCTL_STRICT_ARGS_MODE"
_GLOBALS = Synopsis(
    "[--path=<path>] [--url=<url>] [--user=<id>] [--[no-]color] "
    "[--debug[=<group>]] [--quiet]"
)


class RuntimeConfig:
    """Read-only view of the global runtime configuration."""

    def __init__(self, values, strict):
        self._values = dict(values)
        self._strict = strict

    def path(self):
        return self._values.get("path")

    def url(self):
        return self._values.get("url")

    def user(self):
        return self._values.get("user")

    def color(self):
        return self._values.get("color", True)

    def debug(self):
        return bool(self._values.get("debug", False))

    def quiet(self):
        return bool(self._values.get("quiet", False))

    def strict(self):
        return self._strict

    def as_dict(self):
        return {
            "path": self.path(),
            "url": self.url(),
            "user": self.user(),
            "color": self.color(),
            "debug": self.debug(),
            "quiet": self.quiet(),
            "strict_args_mode": self.strict(),
        }


def extract(items, env):
    """Split global parameters out of ``items``.

    Returns ``(RuntimeConfig, remaining_tokens)``. In strict mode only tokens
    before the first positional word are considered global.
    """
    strict = bool(env.get(_STRICT_ENV, ""))
    values = {}
    remaining = []
    seen_positional = False
    for token in items:
        if not token.is_option():
            seen_positional = True
            remaining.append(token)
            continue
        if strict and seen_positional:
            remaining.append(token)
            continue
        key, value, status = _GLOBALS.interpret(token.name, token.value)
        if status == Synopsis.UNKNOWN:
            remaining.append(token)
        elif status == Synopsis.OK:
            values[key] = value
        else:
            raise CliError(_messages.global_parameter_error(
                key, needs_value=(status == Synopsis.NEEDS_VALUE)))
    return RuntimeConfig(values, strict), remaining
