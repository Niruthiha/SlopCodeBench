"""Python environment discovery.

Secret: where Python installations and virtualenvs are looked for (the
running interpreter, ``PATH``, conventional install and virtualenv
locations), how an executable is asked about itself (a subprocess printing
its version, prefixes and ``sys.path``), what makes it a virtualenv, and how
found environments are deduplicated and ordered.
"""

import json
import os
import re
import shutil
import subprocess
import sys

_WINDOWS = os.name == "nt"
_EXECUTABLE = re.compile(r"^python(\d+(\.\d+)?)?(\.exe)?$", re.IGNORECASE)
_PROBE = (
    "import json, sys\n"
    "print(json.dumps({'version': '%d.%d.%d' % tuple(sys.version_info[:3]),"
    " 'prefix': sys.prefix,"
    " 'base_prefix': getattr(sys, 'base_prefix', sys.prefix),"
    " 'real_prefix': getattr(sys, 'real_prefix', None),"
    " 'sys_path': sys.path}))\n"
)
_TIMEOUT = 15


class Environment:
    def __init__(self, executable, version, is_virtualenv, prefix=None, sys_path=None):
        self.executable = executable
        self.version = version
        self.is_virtualenv = is_virtualenv
        self.prefix = prefix
        self.sys_path = sys_path or []

    def summary(self):
        return {"executable": self.executable, "version": self.version,
                "is_virtualenv": self.is_virtualenv}

    def details(self):
        return dict(self.summary(), prefix=self.prefix, sys_path=list(self.sys_path))


_PROBED = {}


def probe(executable):
    """The Environment of the Python at path ``executable``, or None when it
    is not a working Python interpreter."""
    executable = os.path.abspath(executable)
    if executable in _PROBED:
        return _PROBED[executable]
    found = None
    if os.path.isfile(executable) and os.access(executable, os.X_OK):
        try:
            completed = subprocess.run([executable, "-c", _PROBE], stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       timeout=_TIMEOUT, cwd=os.path.dirname(executable))
            data = json.loads(completed.stdout.decode("utf-8", errors="replace")
                              .strip().splitlines()[-1]) if completed.returncode == 0 else None
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            data = None
        if isinstance(data, dict) and isinstance(data.get("version"), str):
            prefix = data.get("prefix")
            virtual = bool(data.get("real_prefix")) or (
                prefix is not None and prefix != data.get("base_prefix"))
            paths = [p for p in data.get("sys_path") or [] if isinstance(p, str) and p]
            found = Environment(executable, data["version"], virtual, prefix, paths)
    _PROBED[executable] = found
    return found


def find_executable(name):
    """Absolute path of the executable called (or found at) ``name``, or None."""
    if os.sep in name or (os.altsep and os.altsep in name):
        return os.path.abspath(name) if os.path.isfile(name) else None
    found = shutil.which(name)
    return os.path.abspath(found) if found else None


def default_executable():
    return find_executable("python3") or find_executable("python") or sys.executable


def system_environments():
    """Python installations on this system (newest first)."""
    found = []
    seen = set()
    for executable in _system_candidates():
        key = os.path.realpath(executable)
        if key in seen:
            continue
        environment = probe(executable)
        if environment is not None:
            seen.add(key)
            found.append(environment)
    return _ordered(found)


def virtualenvs(path=None, project_root=None):
    """Virtualenvs below ``path`` and in the conventional locations (newest first)."""
    directories = []
    if path:
        directories += _subdirectories(path)
    directories += _subdirectories(os.path.join(os.path.expanduser("~"), ".virtualenvs"))
    for base in dict.fromkeys([os.getcwd(), project_root or os.getcwd()]):
        directories += [os.path.join(base, ".venv"), os.path.join(base, "venv")]
    found = []
    seen = set()
    for directory in directories:
        key = os.path.realpath(directory)
        if key in seen:
            continue
        environment = _virtualenv(directory)
        if environment is not None:
            seen.add(key)
            found.append(environment)
    return _ordered(found)


def site_directories(executable):
    """The package directories (``site-packages``) on the ``sys.path`` of the
    Python at ``executable``."""
    environment = probe(executable) if executable else None
    if environment is None:
        return []
    return [p for p in environment.sys_path
            if os.path.basename(os.path.normpath(p)) in ("site-packages", "dist-packages")
            and os.path.isdir(p)]


def _virtualenv(directory):
    if not os.path.isdir(directory):
        return None
    if _WINDOWS:
        names = [os.path.join("Scripts", "python.exe")]
    else:
        names = [os.path.join("bin", "python"), os.path.join("bin", "python3")]
    for name in names:
        executable = os.path.abspath(os.path.join(directory, name))
        if not os.path.isfile(executable):
            continue
        environment = probe(executable)
        if environment is not None:
            return Environment(executable, environment.version, True,
                               environment.prefix, environment.sys_path)
        version = _configured_version(directory)
        if version is not None:
            return Environment(executable, version, True, os.path.abspath(directory))
    return None


def _configured_version(directory):
    """The Python version recorded in a virtualenv's ``pyvenv.cfg``, or None."""
    try:
        with open(os.path.join(directory, "pyvenv.cfg"), encoding="utf-8",
                  errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and key.strip() in ("version", "version_info") and value.strip():
            return value.strip()
    return None


def _subdirectories(path):
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return []
    return [os.path.join(path, name) for name in names
            if os.path.isdir(os.path.join(path, name))]


def _system_candidates():
    candidates = []
    directories = os.environ.get("PATH", "").split(os.pathsep)
    if _WINDOWS:
        directories += [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python")]
    else:
        directories += ["/usr/local/bin", "/usr/bin", "/bin", "/opt/homebrew/bin",
                        "/opt/local/bin"]
        directories += [os.path.join(d, "bin") for d in _subdirectories(
            os.path.join(os.path.expanduser("~"), ".pyenv", "versions"))]
    for directory in dict.fromkeys(d for d in directories if d):
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            if _EXECUTABLE.match(name):
                candidates.append(os.path.abspath(os.path.join(directory, name)))
    if sys.executable:  # the running interpreter, when not found otherwise
        candidates.append(os.path.abspath(sys.executable))
    return candidates


def _version_key(version):
    numbers = []
    for part in re.split(r"[.\-+]", version):
        match = re.match(r"\d+", part)
        numbers.append(int(match.group()) if match else 0)
    return tuple(numbers)


def _ordered(environments):
    environments = sorted(environments, key=lambda e: e.executable)
    return sorted(environments, key=lambda e: _version_key(e.version), reverse=True)
