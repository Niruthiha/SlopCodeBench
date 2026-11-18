"""Global settings, persistent project configuration and the import search path.

The command line builds one `Options` object per invocation and activates it;
the analysis layers (importer, inferrer, completer) read it through `current()`.
"""
import contextlib
import json
import os
import sys
from dataclasses import dataclass, fields

from .errors import SithError

CONFIG_DIRECTORY = ".sith"
CONFIG_FILE = "project.json"

_TRUE = "true"
_FALSE = "false"


@dataclass
class Settings:
    """Behavior switches (`--setting key=value`, or keys of the project configuration)."""

    case_insensitive: bool = True
    dynamic_params: bool = True
    smart_sys_path: bool = True
    add_bracket: bool = False

    @classmethod
    def names(cls):
        return [f.name for f in fields(cls)]

    def update(self, values):
        for name, value in values.items():
            setattr(self, name, value)
        return self


def parse_setting(text):
    """("name", value) for a `key=value` command-line setting; SithError if invalid."""
    name, separator, raw = text.partition("=")
    name = name.strip()
    if not separator:
        raise SithError(f"invalid setting {text!r} (expected key=value)")
    if name not in Settings.names():
        raise SithError(f"unknown setting {name!r} (expected one of {', '.join(Settings.names())})")
    value = raw.strip().lower()
    if value not in (_TRUE, _FALSE):
        raise SithError(f"invalid value {raw!r} for setting {name!r} (expected true or false)")
    return name, value == _TRUE


def parse_settings(texts):
    values = {}
    for text in texts or []:
        name, value = parse_setting(text)
        values[name] = value
    return values


# -- project configuration ---------------------------------------------------------------


@dataclass
class ProjectConfig:
    """The contents of `<project>/.sith/project.json`."""

    environment_path: str = ""
    sys_path: list = None
    added_sys_path: list = None
    smart_sys_path: bool = True
    # Other settings stored in the file (overridden by `--setting`).
    settings: dict = None

    def __post_init__(self):
        self.sys_path = list(self.sys_path or [])
        self.added_sys_path = list(self.added_sys_path or [])
        self.settings = dict(self.settings or {})

    @classmethod
    def from_dict(cls, data):
        """A config from parsed JSON, ignoring fields of the wrong type."""
        config = cls()
        if not isinstance(data, dict):
            return config
        environment = data.get("environment_path")
        if isinstance(environment, str):
            config.environment_path = environment
        for name in ("sys_path", "added_sys_path"):
            paths = data.get(name)
            if isinstance(paths, list):
                setattr(config, name, [p for p in paths if isinstance(p, str) and p])
        nested = data.get("settings")
        for source in (nested if isinstance(nested, dict) else {}, data):
            for name in Settings.names():
                if isinstance(source.get(name), bool):
                    config.settings[name] = source[name]
        if isinstance(data.get("smart_sys_path"), bool):
            config.smart_sys_path = data["smart_sys_path"]
        config.settings["smart_sys_path"] = config.smart_sys_path
        return config


def config_path(root):
    return os.path.join(os.path.abspath(root), CONFIG_DIRECTORY, CONFIG_FILE)


def read_config_file(path):
    """The parsed JSON object stored at `path` (SithError when unreadable or invalid)."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise SithError(f"cannot read project configuration {path}: {error}") from error
    if not isinstance(data, dict):
        raise SithError(f"invalid project configuration {path}: expected a JSON object")
    return data


def load_project_config(root):
    """The configuration of the project at `root`, or None when it has none.

    A broken configuration file is reported on STDERR and otherwise ignored:
    analysis must keep working.
    """
    path = config_path(root)
    if not os.path.isfile(path):
        return None
    try:
        return ProjectConfig.from_dict(read_config_file(path))
    except SithError as error:
        print(f"warning: {error}", file=sys.stderr)
        return None


def init_project(directory, environment=None, sys_path=None, added_sys_path=None):
    """Create or update `<directory>/.sith/project.json`; returns (path, config dict).

    Only the fields that are given (not None) overwrite those of an existing file.
    """
    directory = os.path.abspath(directory)
    if os.path.exists(directory) and not os.path.isdir(directory):
        raise SithError(f"not a directory: {directory}")
    path = config_path(directory)
    data = read_config_file(path) if os.path.exists(path) else {}
    defaults = {"environment_path": "", "sys_path": [], "added_sys_path": [],
                "smart_sys_path": True}
    for name, value in defaults.items():
        data.setdefault(name, value)
    if environment is not None:
        data["environment_path"] = environment
    if sys_path is not None:
        data["sys_path"] = sys_path
    if added_sys_path is not None:
        data["added_sys_path"] = added_sys_path
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
    except OSError as error:
        raise SithError(f"cannot write {path}: {error}") from error
    return path, data


# -- options of one invocation ----------------------------------------------------------


@dataclass
class SearchPath:
    """Import roots: `early` ones are searched before the standard library, `late` ones after.

    `named` roots are those module names are made relative to (besides the project root).
    """

    early: list
    late: list
    named: list


class Options:
    def __init__(self, settings=None, project=None, root=None, file=None, namespaces=None):
        self.settings = settings or Settings()
        self.project = project
        self.root = os.path.abspath(root) if root else None
        self.file = os.path.abspath(file) if file else None
        self.namespaces = namespaces

    @classmethod
    def load(cls, root, file=None, cli_settings=None, namespaces=None):
        """Options for a command on the project at `root`: defaults < project config < CLI."""
        project = load_project_config(root) if root and os.path.isdir(root) else None
        settings = Settings()
        if project is not None:
            settings.update(project.settings)
        settings.update(cli_settings or {})
        return cls(settings, project, root, file, namespaces)

    @property
    def environment_path(self):
        return self.project.environment_path if self.project else ""

    def search_path(self, project_dir):
        """The SearchPath for imports in the project rooted at `project_dir`."""
        project_dir = os.path.abspath(project_dir)
        project = self.project or ProjectConfig()

        def resolve(path):
            return os.path.normpath(os.path.join(project_dir, os.path.expanduser(path)))

        explicit = [resolve(p) for p in project.sys_path]
        added = [resolve(p) for p in project.added_sys_path]
        if explicit:
            early, late = explicit, []
        elif self.settings.smart_sys_path:
            early, late = [project_dir], self._parent_directories(project_dir)
        else:
            early, late = [], []
        late = late + added
        return SearchPath(_unique(early), _unique(late), _unique([project_dir] + explicit + added))

    def _parent_directories(self, project_dir):
        """Directories from the project root (exclusive) down to the analyzed file's directory."""
        if not self.file:
            return []
        directory = os.path.dirname(self.file)
        found = []
        while directory != project_dir and directory.startswith(project_dir.rstrip(os.sep) + os.sep):
            found.append(directory)
            directory = os.path.dirname(directory)
        return list(reversed(found))


def _unique(paths):
    seen = set()
    result = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


_CURRENT = [Options()]


def current():
    """The Options of the running command (defaults outside of the command line)."""
    return _CURRENT[-1]


@contextlib.contextmanager
def activate(options):
    _CURRENT.append(options)
    try:
        yield options
    finally:
        _CURRENT.pop()
