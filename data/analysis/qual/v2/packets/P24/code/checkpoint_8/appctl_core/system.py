"""Host environment.

Secret: how the operating system is detected, which interpreter runs
appctl (and the environment variables overriding it), where the running
binary lives and whether it is a distribution archive, and which host
requirements (container runtime, compose tool, interpreter version) are
checked, with how many attempts and which back-off.
"""

import os
import platform as _platform
import shutil
import sys
import time
import zipfile

from . import containers, process, semver
from . import messages as _messages

RUNTIME_BIN_ENV = "APPCTL_RUNTIME_BIN"
RUNTIME_BIN_USED_ENV = "APPCTL_RUNTIME_BIN_USED"
FALLBACK_RUNTIME_BIN = "python3"
MIN_RUNTIME_VERSION = "3.8.0"
MIN_COMPOSE_VERSION = "2.0.0"
COMPOSE_BINARY = "docker-compose"
# Attempts at reaching the container runtime and the pause before each retry.
RUNTIME_CHECK_DELAYS = (0.2, 0.4, 0.8)
_ENTRY_POINT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "appctl.py")
_GROUP = "bootstrap"


# --- platform ------------------------------------------------------------------

def is_darwin():
    """Whether appctl runs on macOS (read at call time)."""
    return sys.platform == "darwin" or _platform.system() == "Darwin"


def os_description():
    uname = _platform.uname()
    return " ".join(p for p in (uname.system, uname.release, uname.version,
                                uname.machine) if p)


def shell(env):
    return env.get("SHELL") or env.get("COMSPEC") or None


# --- runtime binary --------------------------------------------------------------

def runtime_binary(env=None):
    """The interpreter used to run appctl: ``APPCTL_RUNTIME_BIN``, then
    ``APPCTL_RUNTIME_BIN_USED``, then the running interpreter, then the
    fallback command name."""
    env = os.environ if env is None else env
    for name in (RUNTIME_BIN_ENV, RUNTIME_BIN_USED_ENV):
        value = (env.get(name) or "").strip()
        if value:
            return value
    if sys.executable:
        return sys.executable
    return FALLBACK_RUNTIME_BIN


def runtime_version():
    return _platform.python_version()


# --- binary ----------------------------------------------------------------------

def archive_path():
    """The distribution archive appctl runs from, or ``None`` when it runs
    from a source tree."""
    path = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isfile(path):
            return path if zipfile.is_zipfile(path) else None
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def install_dir():
    """Directory containing the appctl code."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def binary_path(env=None):
    """The file replaced by a self-update and run by child invocations."""
    env = os.environ if env is None else env
    override = env.get("APPCTL_BINARY_PATH")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return archive_path() or _ENTRY_POINT


def is_writable(path):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    return (os.path.isfile(path) and os.access(path, os.W_OK)
            and os.access(directory, os.W_OK))


# --- requirements ----------------------------------------------------------------

def _which(name, env):
    return shutil.which(name, path=env.get("PATH") or None)


def _version_of(argv_list, env, out):
    for argv in argv_list:
        result = process.run(argv, env=env, out=out)
        if result.succeeded:
            version = semver.parse(result.stdout)
            if version is not None:
                return version
    return None


class Requirements:
    """Checks that the host can run appctl. ``sleep`` is the pause used
    between attempts at reaching the container runtime."""

    def __init__(self, env, out, sleep=None, delays=None):
        self.env = dict(env)
        self.out = out
        self.sleep = sleep or time.sleep
        self.delays = RUNTIME_CHECK_DELAYS if delays is None else tuple(delays)

    def _runtime_responds(self):
        binary = _which(containers.RUNTIME, self.env)
        if binary is None:
            return False
        return process.run([binary, "ps"], env=self.env, out=self.out).succeeded

    def runtime_running(self):
        """Ask the container runtime, retrying with increasing pauses."""
        if self._runtime_responds():
            return True
        for delay in self.delays:
            self.out.debug(f"Container runtime not responding; retrying in {delay}s.",
                           group=_GROUP)
            self.sleep(delay)
            if self._runtime_responds():
                return True
        return False

    def compose_version(self):
        """``(installed, version)`` of the compose tool: the standalone
        binary when present, otherwise the runtime plugin."""
        binary = _which(COMPOSE_BINARY, self.env)
        if binary is not None:
            version = _version_of([[binary, "version", "--short"], [binary, "version"],
                                   [binary, "--version"]], self.env, self.out)
            return True, version
        runtime = _which(containers.RUNTIME, self.env)
        if runtime is not None:
            version = _version_of([[runtime, "compose", "version", "--short"],
                                   [runtime, "compose", "version"]], self.env, self.out)
            if version is not None:
                return True, version
        return False, None

    def errors(self):
        """Every unmet requirement, as user-facing messages."""
        errors = []
        if not self.runtime_running():
            errors.append(_messages.container_runtime_unavailable(is_darwin()))
        installed, version = self.compose_version()
        if not installed:
            errors.append(_messages.compose_not_installed())
        elif version is None or version < semver.parse(MIN_COMPOSE_VERSION):
            errors.append(_messages.compose_too_old(version, MIN_COMPOSE_VERSION))
        current = semver.parse(runtime_version())
        if current is None or current < semver.parse(MIN_RUNTIME_VERSION):
            errors.append(_messages.runtime_too_old(runtime_version(), MIN_RUNTIME_VERSION))
        return errors

    def check(self):
        """Report every unmet requirement; return whether all are met."""
        errors = self.errors()
        for error in errors:
            self.out.error(error)
        return not errors
