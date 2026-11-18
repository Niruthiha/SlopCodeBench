"""The `env` commands: discovering Python installations and virtual environments."""
import concurrent.futures
import glob
import json
import os
import re
import shutil
import subprocess
import sys

from .errors import SithError

DEFAULT_EXECUTABLE = "python3"
_TIMEOUT = 15
_EXECUTABLE_NAME = re.compile(r"python(\d+(\.\d+)?)?(\.exe)?", re.IGNORECASE)
_VIRTUALENV_DIRECTORIES = (".venv", "venv")
# Run inside the inspected interpreter; must stay compatible with old Pythons.
_PROBE = """\
import json, platform, sys
base = getattr(sys, "real_prefix", None) or getattr(sys, "base_prefix", sys.prefix)
print(json.dumps({
    "executable": sys.executable,
    "version": platform.python_version(),
    "version_info": [sys.version_info[0], sys.version_info[1], sys.version_info[2],
                     sys.version_info[3], sys.version_info[4]],
    "is_virtualenv": sys.prefix != base,
    "prefix": sys.prefix,
    "sys_path": [p for p in sys.path if p],
}))
"""
_RELEASE_LEVELS = {"alpha": 0, "beta": 1, "candidate": 2, "final": 3}


class Environment:
    """A Python interpreter and what it reports about itself."""

    def __init__(self, executable, info):
        self.executable = executable
        self.version = info["version"]
        major, minor, micro, level, serial = info["version_info"]
        self.version_key = (major, minor, micro, _RELEASE_LEVELS.get(level, 3), serial)
        self.is_virtualenv = bool(info["is_virtualenv"])
        self.prefix = info["prefix"]
        self.sys_path = list(info["sys_path"])

    @property
    def sort_key(self):
        return tuple(-part for part in self.version_key), self.executable

    def to_dict(self, details=False):
        result = {"executable": self.executable, "version": self.version,
                  "is_virtualenv": self.is_virtualenv}
        if details:
            result.update(prefix=self.prefix, sys_path=self.sys_path)
        return result


def _bin_directory():
    return "Scripts" if os.name == "nt" else "bin"


def _executable_name():
    return "python.exe" if os.name == "nt" else "python"


def _is_executable(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)


def probe(executable):
    """The Environment of the interpreter at `executable`, or None if it is not a working Python."""
    for flags in (["-I"], ["-E", "-s"]):
        try:
            completed = subprocess.run([executable, *flags, "-c", _PROBE], capture_output=True,
                                       text=True, timeout=_TIMEOUT, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        if completed.returncode != 0:
            continue
        try:
            lines = completed.stdout.strip().splitlines()
            return Environment(executable, json.loads(lines[-1]))
        except (ValueError, KeyError, TypeError, IndexError):
            return None
    return None


def _probe_all(executables):
    """{executable: Environment} for those of `executables` that are working Pythons."""
    executables = list(dict.fromkeys(executables))
    if not executables:
        return {}
    workers = min(16, len(executables))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        found = dict(zip(executables, pool.map(probe, executables)))
    return {path: environment for path, environment in found.items() if environment is not None}


# -- env list ------------------------------------------------------------------------------


def _system_candidates():
    """Absolute paths of the Python executables found on PATH and in usual locations."""
    directories = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    home = os.path.expanduser("~")
    directories += ["/usr/bin", "/usr/local/bin", "/opt/homebrew/bin", "/opt/local/bin"]
    directories += sorted(glob.glob(os.path.join(home, ".pyenv", "versions", "*", "bin")))
    for variable in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        if os.environ.get(variable):
            directories.append(os.path.join(os.environ[variable], _bin_directory()))
    candidates = []
    for directory in directories:
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            path = os.path.abspath(os.path.join(directory, name))
            if _EXECUTABLE_NAME.fullmatch(name) and _is_executable(path):
                candidates.append(path)
    for path in (sys.executable, getattr(sys, "_base_executable", None)):
        if path and _is_executable(path):
            candidates.append(os.path.abspath(path))
    return candidates


def list_environments():
    """Python installations, one per resolved executable, newest version first."""
    groups = {}
    for path, environment in _probe_all(_system_candidates()).items():
        groups.setdefault(os.path.realpath(path), []).append(environment)
    # Of several paths to one interpreter, prefer the installation over virtualenvs,
    # and paths through real directories over symlinked ones (e.g. /bin -> /usr/bin).
    chosen = [min(group, key=_preference) for group in groups.values()]
    return sorted(chosen, key=lambda e: e.sort_key)


def _preference(environment):
    directory = os.path.dirname(environment.executable)
    return environment.is_virtualenv, os.path.realpath(directory) != directory, environment.executable


# -- env find-virtualenvs -----------------------------------------------------------------


def _virtualenv_executable(directory):
    path = os.path.join(directory, _bin_directory(), _executable_name())
    return os.path.abspath(path) if _is_executable(path) else None


def _subdirectories(directory):
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    return [os.path.join(directory, name) for name in names
            if os.path.isdir(os.path.join(directory, name))]


def find_virtualenvs(path=None, project=None):
    """Virtualenvs in `path`, `~/.virtualenvs` and the `.venv`/`venv` of the cwd and project."""
    directories = []
    if path is not None:
        directories += _subdirectories(os.path.expanduser(path))
    directories += _subdirectories(os.path.join(os.path.expanduser("~"), ".virtualenvs"))
    for base in dict.fromkeys(os.path.abspath(d) for d in (os.getcwd(), project or os.getcwd())):
        directories += [os.path.join(base, name) for name in _VIRTUALENV_DIRECTORIES]
    executables = [e for e in map(_virtualenv_executable, directories) if e]
    environments = {}
    for executable, environment in _probe_all(executables).items():
        if not environment.is_virtualenv:
            continue
        # Every virtualenv links to its base interpreter: tell them apart by location.
        location = os.path.join(os.path.realpath(os.path.dirname(executable)),
                                os.path.basename(executable))
        environments.setdefault(location, environment)
    return sorted(environments.values(), key=lambda e: e.sort_key)


# -- env info -----------------------------------------------------------------------------


def environment_info(executable=None, default=None):
    """The Environment of `executable` (a path or a command name).

    Without one, `default` (the project's environment) or else `python3` is used.
    """
    requested = executable or default or DEFAULT_EXECUTABLE
    path = _find_executable(requested)
    if path is None and not executable and not default:
        path = sys.executable  # no `python3` on PATH: the running interpreter
    if path is None:
        raise SithError(f"Python executable not found: {requested}")
    environment = probe(path)
    if environment is None:
        raise SithError(f"not a valid Python executable: {requested}")
    return environment


def _find_executable(name):
    expanded = os.path.expanduser(name)
    if os.path.isdir(expanded):  # a virtualenv or installation prefix
        return _virtualenv_executable(expanded)
    if os.sep in expanded or (os.altsep and os.altsep in expanded) or os.path.exists(expanded):
        return os.path.abspath(expanded) if _is_executable(expanded) else None
    found = shutil.which(expanded)
    return os.path.abspath(found) if found else None
