"""Loading of global/project YAML config files and alias definitions."""

import json
import os
import re
from dataclasses import dataclass, field

import yaml

from .errors import AppctlError

CONFIG_PATH_ENV = "APPCTL_CONFIG_PATH"
ROOT_DIR_ENV = "APPCTL_ROOT_DIR"
PACKAGES_DIR_ENV = "APPCTL_PACKAGES_DIR"
RUNTIME_ALIAS_ENV = "APPCTL_RUNTIME_ALIAS"

PROJECT_CONFIG_FILES = ("appctl.local.yml", "appctl.yml")
ALIAS_RE = re.compile(r"^@[A-Za-z0-9_.\-]+$")
ALL_ALIAS = "@all"
META_KEY = "_"

# Keys the global config file must always define, with their defaults.
REQUIRED_GLOBAL_KEYS = (("locale", "en_US"), ("installer_version", "stable"))


def is_alias(name):
    return isinstance(name, str) and bool(ALIAS_RE.match(name))


def alias_sort_key(name):
    return (name.lower(), name)


# -- locations -----------------------------------------------------------


def root_dir(environ):
    value = environ.get(ROOT_DIR_ENV)
    if value:
        return value
    return os.path.join(os.path.expanduser("~"), ".appctl")


def global_config_path(environ):
    value = environ.get(CONFIG_PATH_ENV)
    if value:
        return value
    return os.path.join(root_dir(environ), "config", "config.yml")


def packages_dir(environ):
    value = environ.get(PACKAGES_DIR_ENV)
    if value:
        return value
    return os.path.join(root_dir(environ), "packages")


def find_project_config(cwd):
    """Search upward from ``cwd``; the first directory with a config wins."""
    directory = os.path.abspath(cwd)
    while True:
        for name in PROJECT_CONFIG_FILES:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent


# -- auto-creation ---------------------------------------------------------


def _read_mapping(path):
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AppctlError(f"Unable to parse the config file '{path}': {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise AppctlError(f"The config file '{path}' must contain a YAML mapping.")
    return data, text


def ensure_global_config(path, strict=True):
    """Add missing required keys to the global config file, creating it.

    Write failures raise :class:`AppctlError` unless ``strict`` is false.
    """
    try:
        if os.path.exists(path):
            data, text = _read_mapping(path)
        else:
            data, text = {}, ""
        missing = [(k, v) for k, v in REQUIRED_GLOBAL_KEYS if k not in data]
        if not missing:
            return
        if text and not text.endswith("\n"):
            text += "\n"
        text += "".join(f"{key}: {value}\n" for key, value in missing)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    except OSError as exc:
        if strict:
            reason = exc.strerror or str(exc)
            raise AppctlError(f"Unable to write the config file '{path}': {reason}.") from exc


# -- YAML loading with inheritance -------------------------------------------


def _merge(base, override, append_arrays):
    """Overlay ``override`` on ``base``; nested mappings merge recursively."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _merge(base[key], value, append_arrays) if key in base else value
        return merged
    if append_arrays and isinstance(base, list) and isinstance(override, list):
        return base + override
    return override


def _absolutize_alias_paths(data, directory):
    for key, value in data.items():
        if is_alias(key) and isinstance(value, dict):
            path = value.get("path")
            if isinstance(path, str) and path and "ssh" not in value:
                value["path"] = os.path.normpath(os.path.join(directory, os.path.expanduser(path)))


def load_config_file(path, accumulated=None, _seen=None):
    """Merge the YAML file at ``path`` (and its ancestors) over ``accumulated``."""
    accumulated = dict(accumulated or {})
    if not path:
        return accumulated
    path = os.path.abspath(path)
    seen = set(_seen or ())
    if path in seen or not os.path.isfile(path):
        return accumulated
    seen.add(path)
    try:
        data, _ = _read_mapping(path)
    except OSError:
        return accumulated
    directory = os.path.dirname(path)
    meta = data.pop(META_KEY, None)
    meta = meta if isinstance(meta, dict) else {}
    inherit = meta.get("inherit")
    if isinstance(inherit, str) and inherit:
        base = os.path.join(directory, os.path.expanduser(inherit))
        accumulated = load_config_file(base, accumulated, seen)
    _absolutize_alias_paths(data, directory)
    return _merge(accumulated, data, meta.get("merge") is True)


# -- aliases -------------------------------------------------------------------


def runtime_aliases(environ, cwd):
    raw = environ.get(RUNTIME_ALIAS_ENV)
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    aliases = {k: v for k, v in decoded.items() if is_alias(k)}
    _absolutize_alias_paths(aliases, cwd)
    return aliases


def collect_aliases(config, extra=None):
    """Return ``{name: definition}``, registering ``@all`` when needed.

    A definition is either a mapping of connection parameters or a list
    of alias names (a group).
    """
    aliases = {}
    for key, value in list(config.items()) + list((extra or {}).items()):
        if not is_alias(key):
            continue
        if isinstance(value, list):
            aliases[key] = [str(v) for v in value]
        elif isinstance(value, dict):
            aliases[key] = dict(value)
        elif value is None:
            aliases[key] = {}
        else:
            aliases[key] = value
    if aliases and ALL_ALIAS not in aliases:
        aliases[ALL_ALIAS] = None  # implicit: every registered alias
    return aliases


# -- entry point ---------------------------------------------------------------


@dataclass
class LoadedConfig:
    global_path: str = None
    project_path: str = None
    global_config: dict = field(default_factory=dict)
    merged: dict = field(default_factory=dict)
    aliases: dict = field(default_factory=dict)
    packages_dir: str = None


def load(environ, cwd=None):
    cwd = cwd or os.getcwd()
    global_path = global_config_path(environ)
    explicit = bool(environ.get(CONFIG_PATH_ENV) or environ.get(ROOT_DIR_ENV))
    ensure_global_config(global_path, strict=explicit)
    global_config = load_config_file(global_path)
    project_path = find_project_config(cwd)
    if project_path and os.path.abspath(project_path) == os.path.abspath(global_path):
        project_path = None
    merged = load_config_file(project_path, global_config)
    return LoadedConfig(
        global_path=global_path,
        project_path=project_path,
        global_config=global_config,
        merged=merged,
        aliases=collect_aliases(merged, runtime_aliases(environ, cwd)),
        packages_dir=packages_dir(environ),
    )
