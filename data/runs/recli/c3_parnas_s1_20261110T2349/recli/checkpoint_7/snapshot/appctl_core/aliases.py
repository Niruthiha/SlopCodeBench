"""Alias registry.

Secret: the alias name syntax, how runtime aliases override file aliases,
when ``@all`` is registered automatically, how groups are expanded and
validated, and the order in which broadcast targets run.
"""

import json
import re

from . import messages as _messages
from .errors import CliError
from .suggest import suggest

_ALIAS_NAME = re.compile(r"^@[A-Za-z0-9_.\-]+$")
_RUNTIME_ENV = "APPCTL_RUNTIME_ALIAS"
ALL = "@all"
_AUTO_ALL = "Run command against every registered alias."


def is_alias_name(text):
    return isinstance(text, str) and bool(_ALIAS_NAME.match(text))


def _sort_key(name):
    return (name.casefold(), name)


def runtime_aliases(env):
    """Alias definitions from the runtime environment variable."""
    raw = env.get(_RUNTIME_ENV)
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    result = {}
    for name, value in decoded.items():
        if not is_alias_name(name):
            continue
        if isinstance(value, list):
            result[name] = [str(v) for v in value if v is not None]
        elif isinstance(value, dict):
            result[name] = dict(value)
        elif value is None:
            result[name] = {}
    return result


class Target:
    """Resolution of an alias: either a connection or a group of aliases."""

    def __init__(self, name, connection=None, members=None):
        self.name = name
        self.connection = connection
        self.members = members

    def is_group(self):
        return self.members is not None


class AliasRegistry:
    def __init__(self, file_aliases, runtime=None):
        self._defs = dict(file_aliases)
        self._defs.update(runtime or {})
        if self._defs and ALL not in self._defs:
            self._defs[ALL] = _AUTO_ALL

    def names(self):
        return sorted(self._defs, key=_sort_key)

    def is_registered(self, name):
        return name in self._defs

    def definitions(self):
        return dict(self._defs)

    def definition(self, name):
        return self._defs.get(name)

    def _broadcast_members(self):
        return [name for name in self.names()
                if name != ALL and isinstance(self._defs[name], dict)]

    def resolve(self, name):
        """Return the ``Target`` for alias ``name`` or raise ``CliError``."""
        if name == ALL and not self._defs:
            raise CliError(_messages.alias_all_without_aliases())
        if name not in self._defs:
            raise CliError(_messages.alias_not_found(
                name, suggest(name, list(self._defs))))
        value = self._defs[name]
        if name == ALL and value == _AUTO_ALL:
            return Target(name, members=self._broadcast_members())
        if isinstance(value, list):
            members = list(dict.fromkeys(value))
            invalid = [m for m in members if m not in self._defs]
            if invalid:
                raise CliError(_messages.alias_group_invalid(name, invalid))
            return Target(name, members=members)
        return Target(name, connection=dict(value) if isinstance(value, dict) else {})
