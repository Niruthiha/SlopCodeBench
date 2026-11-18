"""Settings and project configuration.

Secret: which settings exist and how their values are spelled on the command
line, where a project's persistent configuration lives (``.sith/project.json``
below the project root) and how it is read, merged and written, and the
precedence of command-line settings over project configuration over defaults.
The settings of the running command are kept as the *active* settings.
"""

import json
import os

CONFIG_DIRECTORY = ".sith"
CONFIG_FILE = "project.json"

# Settings accepted by ``--setting key=value`` (all boolean).
SETTINGS = {
    "case_insensitive": True,
    "dynamic_params": True,
    "smart_sys_path": True,
    "add_bracket": False,
}

# Fields of a project configuration file, with their defaults.
PROJECT_FIELDS = {
    "environment_path": "",
    "sys_path": [],
    "added_sys_path": [],
    "smart_sys_path": True,
}


class ConfigError(Exception):
    """A setting or configuration value is malformed."""


class Settings:
    """The effective configuration of one command."""

    def __init__(self, root=None, values=None, project=None):
        values = dict(SETTINGS, **(values or {}))
        project = dict(_project_defaults(), **(project or {}))
        self.root = os.path.abspath(root) if root else None
        self.case_insensitive = values["case_insensitive"]
        self.dynamic_params = values["dynamic_params"]
        self.smart_sys_path = values["smart_sys_path"]
        self.add_bracket = values["add_bracket"]
        self.environment_path = project["environment_path"] or None
        self.sys_path = [self._absolute(p) for p in project["sys_path"]]
        self.added_sys_path = [self._absolute(p) for p in project["added_sys_path"]]

    def _absolute(self, path):
        path = os.path.expanduser(path)
        if not os.path.isabs(path) and self.root:
            path = os.path.join(self.root, path)
        return os.path.normpath(os.path.abspath(path))


_ACTIVE = None


def activate(settings):
    global _ACTIVE
    _ACTIVE = settings


def active():
    """The settings of the running command (the defaults until activated)."""
    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = Settings()
    return _ACTIVE


def parse_setting(text):
    """``(key, value)`` for a ``key=value`` command-line setting."""
    key, sep, raw = text.partition("=")
    key = key.strip()
    if not sep or key not in SETTINGS:
        raise ConfigError("unknown setting: %s" % text)
    value = _boolean(raw.strip())
    if value is None:
        raise ConfigError("setting %s needs true or false, not %r" % (key, raw))
    return key, value


def resolve(root, overrides):
    """The settings for a command run in project ``root`` (may be None) with
    command-line ``overrides`` (dict of setting -> value)."""
    project = load_project(root) if root else {}
    values = {key: project[key] for key in SETTINGS if isinstance(project.get(key), bool)}
    values.update(overrides)
    return Settings(root, values, {key: project[key] for key in PROJECT_FIELDS
                                   if key in project})


def config_path(root):
    return os.path.join(root, CONFIG_DIRECTORY, CONFIG_FILE)


def load_project(root):
    """The valid entries of the configuration stored for project ``root`` (a
    dict; empty when there is none or it cannot be read)."""
    try:
        with open(config_path(root), "rb") as handle:
            data = json.loads(handle.read().decode("utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    found = {}
    environment = data.get("environment_path")
    if environment is None or isinstance(environment, str):
        found["environment_path"] = environment
    for key in ("sys_path", "added_sys_path"):
        paths = data.get(key)
        if isinstance(paths, list) and all(isinstance(p, str) for p in paths):
            found[key] = list(paths)
    for key in SETTINGS:
        value = data.get(key)
        if isinstance(value, str):
            value = _boolean(value)
        if isinstance(value, bool):
            found[key] = value
    return found


def init_project(directory, updates):
    """Create or update the configuration of project ``directory`` with the
    fields in ``updates``; return ``(path, configuration)``."""
    path = config_path(directory)
    existing = {}
    try:
        with open(path, "rb") as handle:
            existing = json.loads(handle.read().decode("utf-8"))
    except (OSError, ValueError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    configuration = dict(_project_defaults(), **existing)
    configuration.update(updates)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(configuration, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except OSError as exc:
        raise ConfigError("cannot write %s: %s" % (path, exc))
    return path, configuration


def split_paths(text):
    """The entries of a comma-separated path list."""
    return [part.strip() for part in text.split(",") if part.strip()]


def _boolean(text):
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def _project_defaults():
    return {key: list(value) if isinstance(value, list) else value
            for key, value in PROJECT_FIELDS.items()}
