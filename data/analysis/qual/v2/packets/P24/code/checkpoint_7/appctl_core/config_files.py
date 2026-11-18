"""Configuration sources.

Secret: where the global and project config files live, how YAML
inheritance (``_: {inherit, merge}``) and array merging work, how alias
definitions are collected from files, and how missing global defaults are
written back to the global config file.
"""

import errno
import os

from . import config_spec, messages, yaml_lite
from .aliases import is_alias_name
from .errors import CliError

_PROJECT_FILES = ("appctl.local.yml", "appctl.yml")
_AUTO_DEFAULTS = (("locale", "en_US"), ("installer_version", "stable"))
_META_KEY = "_"


class Locations:
    """Filesystem locations derived from the environment."""

    def __init__(self, env):
        root = env.get("APPCTL_ROOT_DIR") or ""
        config = env.get("APPCTL_CONFIG_PATH") or ""
        self.explicit = bool(root or config)
        if not root:
            home = env.get("HOME") or os.path.expanduser("~")
            root = os.path.join(home, ".appctl")
        self.root_dir = _clean(root)
        self.global_config_path = (_clean(config) if config else
                                   os.path.join(self.root_dir, "config", "config.yml"))
        packages = env.get("APPCTL_PACKAGES_DIR") or ""
        self.packages_dir = (_clean(packages) if packages else
                             os.path.join(self.root_dir, "packages"))


def _clean(path):
    path = os.path.expanduser(path)
    stripped = path.rstrip(os.sep)
    return stripped or path


def find_project_config(cwd):
    """Search upward from ``cwd`` for a project config file."""
    directory = os.path.abspath(cwd)
    while True:
        for name in _PROJECT_FILES:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent


def _absolutize(path, base):
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(base, path))


def _arrayify(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _combine(old, new, merge):
    if merge and isinstance(old, list) and isinstance(new, list):
        return old + new
    return new


def _parse(path, text):
    try:
        data = yaml_lite.load(text)
    except yaml_lite.YamlError as exc:
        raise CliError(messages.config_unparsable(path, exc)) from None
    return data if isinstance(data, dict) else ({} if data is None else None)


def _read(path, tolerant=False):
    """Return the mapping stored at ``path`` or ``None`` if absent."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        if tolerant:
            return None
        raise CliError(messages.config_unreadable(path, exc)) from None
    data = _parse(path, text)
    return {} if data is None else data


class LoadedConfig:
    """Values, aliases and other keys collected from config files."""

    def __init__(self):
        self.values = {}
        self.aliases = {}
        self.extra = {}
        self.global_config_path = None
        self.project_config_path = None
        self.files = []

    def merge_file(self, path, tolerant=False, chain=()):
        real = os.path.realpath(path)
        if real in chain:
            return
        data = _read(path, tolerant)
        if data is None:
            return
        meta = data.get(_META_KEY)
        meta = meta if isinstance(meta, dict) else {}
        base = os.path.dirname(os.path.abspath(path))
        inherit = meta.get("inherit")
        if isinstance(inherit, str) and inherit:
            self.merge_file(_inherit_path(inherit, base), tolerant, chain + (real,))
        merge = bool(meta.get("merge"))
        self.files.append(path)
        for key, value in data.items():
            if key == _META_KEY:
                continue
            key = str(key)
            if is_alias_name(key):
                self._merge_alias(key, value, base, merge)
            elif config_spec.file_param(key) is not None:
                self._merge_param(key, value, base, merge)
            else:
                self.extra[key] = _combine(self.extra.get(key), value, merge)

    def _merge_alias(self, name, value, base, merge):
        if isinstance(value, list):
            definition = [str(v) for v in value if v is not None]
        elif isinstance(value, dict):
            definition = {str(k): v for k, v in value.items()}
            path = definition.get("path")
            if isinstance(path, str) and path and "ssh" not in definition:
                definition["path"] = _absolutize(path, base)
        elif value is None:
            definition = {}
        else:
            return
        self.aliases[name] = _combine(self.aliases.get(name), definition, merge)

    def _merge_param(self, key, value, base, merge):
        param = config_spec.file_param(key)
        if param.kind == "list":
            value = _arrayify(value)
        if key == "path" and isinstance(value, str) and value:
            value = _absolutize(value, base)
        self.values[key] = _combine(self.values.get(key), value, merge)


def _inherit_path(inherit, base):
    inherit = os.path.expanduser(inherit)
    if os.path.isabs(inherit):
        return inherit
    relative = os.path.join(base, inherit)
    if not os.path.exists(relative) and os.path.exists(inherit):
        return os.path.abspath(inherit)
    return os.path.normpath(relative)


def ensure_global_defaults(locations):
    """Write missing auto-created keys into the global config file."""
    path = locations.global_config_path
    try:
        text = ""
        if os.path.exists(path):
            if not os.path.isfile(path):
                raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), path)
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        data = _parse(path, text)
        if data is None:
            return
        missing = [(k, v) for k, v in _AUTO_DEFAULTS if k not in data]
        if not missing:
            return
        expected = dict(data, **dict(missing))
        separator = "\n" if text and not text.endswith("\n") else ""
        updated = text + separator + "".join(
            yaml_lite.scalar_line(k, v) for k, v in missing)
        try:
            if yaml_lite.load(updated) != expected:
                raise yaml_lite.YamlError("append changed meaning")
        except yaml_lite.YamlError:
            updated = yaml_lite.dump(expected)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(updated)
    except OSError as exc:
        if locations.explicit:
            raise CliError(messages.config_unwritable(path, exc)) from None


def load(locations, cwd):
    """Load the global config file then the project config file."""
    loaded = LoadedConfig()
    ensure_global_defaults(locations)
    global_path = locations.global_config_path
    if os.path.isfile(global_path):
        loaded.global_config_path = global_path
        loaded.merge_file(global_path, tolerant=not locations.explicit)
    project = find_project_config(cwd)
    if project and not (loaded.global_config_path and
                        os.path.realpath(project) == os.path.realpath(global_path)):
        loaded.project_config_path = project
        loaded.merge_file(project)
    return loaded
