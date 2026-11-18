"""Global runtime parameters.

Secret: which environment variable enables strict arguments mode, which
argv positions may supply global parameters in each mode, and how the
runtime flags, config files, alias parameters and built-in defaults are
layered into one configuration.
"""

from . import config_spec
from . import messages as _messages
from .errors import CliError
from .synopsis import Synopsis

_STRICT_ENV = "APPCTL_STRICT_ARGS_MODE"
_GLOBALS = config_spec.runtime_synopsis()


class RuntimeValues:
    """Global parameters given on the command line."""

    def __init__(self, values, strict, warnings):
        self.values = dict(values)
        self.strict = strict
        self.warnings = list(warnings)

    def debug(self):
        return bool(self.values.get("debug", False))

    def quiet(self):
        return bool(self.values.get("quiet", False))


class RuntimeConfig:
    """Read-only view of the effective global configuration."""

    def __init__(self, values, strict, locations=None, loaded=None, aliases=None):
        self._values = config_spec.defaults()
        self._values.update(values)
        self._strict = strict
        self._locations = locations
        self._loaded = loaded
        self._aliases = aliases

    def get(self, name, default=None):
        return self._values.get(name, default)

    def values(self):
        return dict(self._values)

    def path(self):
        return self._values.get("path")

    def url(self):
        return self._values.get("url")

    def user(self):
        return self._values.get("user")

    def ssh(self):
        return self._values.get("ssh")

    def color(self):
        return self._values.get("color")

    def debug(self):
        return bool(self._values.get("debug", False))

    def quiet(self):
        return bool(self._values.get("quiet", False))

    def strict(self):
        return self._strict

    def disabled_commands(self):
        entries = self._values.get("disabled_commands") or []
        if not isinstance(entries, list):
            entries = [entries]
        return [" ".join(str(e).split()) for e in entries if e is not None]

    def aliases(self):
        """The alias registry, or ``None`` when none was loaded."""
        return self._aliases

    def global_config_path(self):
        return self._loaded.global_config_path if self._loaded else None

    def project_config_path(self):
        return self._loaded.project_config_path if self._loaded else None

    def packages_dir(self):
        return self._locations.packages_dir if self._locations else None

    def root_dir(self):
        return self._locations.root_dir if self._locations else None

    def as_dict(self):
        return {
            "path": self.path(),
            "url": self.url(),
            "user": self.user(),
            "color": self.color(),
            "debug": self.debug(),
            "quiet": self.quiet(),
            "strict_args_mode": self.strict(),
            "global_config_path": self.global_config_path(),
            "project_config_path": self.project_config_path(),
            "packages_dir": self.packages_dir(),
        }


def extract(items, env):
    """Split global parameters out of ``items``.

    Returns ``(RuntimeValues, remaining_tokens)``. In strict mode only tokens
    before the first positional word are considered global.
    """
    strict = bool(env.get(_STRICT_ENV, ""))
    values = {}
    warnings = []
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
            if config_spec.is_deprecated(key):
                warnings.append(_messages.deprecated_global_parameter(key))
        else:
            raise CliError(_messages.global_parameter_error(
                key, needs_value=(status == Synopsis.NEEDS_VALUE)))
    return RuntimeValues(values, strict, list(dict.fromkeys(warnings))), remaining


def layer(runtime, file_values=None, alias_values=None, **context):
    """Combine the sources: runtime > alias > config files > defaults."""
    values = {}
    for key, value in (file_values or {}).items():
        param = config_spec.get(key)
        if param is not None and param.file:
            values[key] = value
    for key, value in (alias_values or {}).items():
        if config_spec.get(key) is not None and key not in ("debug", "quiet"):
            values[key] = value
    values.update(runtime.values)
    return RuntimeConfig(values, runtime.strict, **context)
