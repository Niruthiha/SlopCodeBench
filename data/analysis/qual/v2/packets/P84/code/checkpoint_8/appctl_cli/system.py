"""Host environment: system requirements, the runtime binary and the install location."""

import os
import platform
import re
import shutil
import subprocess
import sys
import time
import zipfile
import zipimport

from . import PROGRAM_NAME, container
from .errors import AppctlError
from .process import run_command
from .upgrade import MIN_COMPOSE_VERSION, compare_semver, compose_version

PRODUCT_NAME = "AppCtl"

RUNTIME_BIN_ENV = "APPCTL_RUNTIME_BIN"
RUNTIME_BIN_USED_ENV = "APPCTL_RUNTIME_BIN_USED"
FALLBACK_RUNTIME = "python3"
MIN_RUNTIME_VERSION = "3.8.0"
RUNTIME_NAME = "Python"

# The container runtime is probed up to RUNTIME_CHECK_ATTEMPTS times; the
# delay before each retry starts at RUNTIME_CHECK_BACKOFF seconds and doubles.
RUNTIME_CHECK_ATTEMPTS = 3
RUNTIME_CHECK_BACKOFF = 0.5
RUNTIME_CHECK_TIMEOUT = 30

RUNTIME_DOWN = "Container runtime is either not installed or not running."
RUNTIME_DARWIN_HINT = ("Please install it with your system package manager "
                       "(e.g. `brew install --cask docker`) and make sure it is running.")
RUNTIME_LINUX_HINT = "Please install and start the container runtime (docker)."

EXEMPT_FAMILIES = ("cli", "config", "help")

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTALL_DIR = os.path.dirname(PACKAGE_DIR)
ENTRY_SCRIPT = os.path.join(INSTALL_DIR, f"{PROGRAM_NAME}.py")

_VERSION_RE = re.compile(r"\d+(?:\.\d+)+")


def is_darwin(platform_name=None):
    return container.is_darwin(platform_name)


# -- install location -------------------------------------------------------------


def archive_path():
    """The archive appctl runs from (archive mode), or ``None`` when run from source."""
    loader = globals().get("__loader__")
    if isinstance(loader, zipimport.zipimporter):
        return os.path.abspath(loader.archive)
    path = PACKAGE_DIR
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    if os.path.isfile(path) and zipfile.is_zipfile(path):
        return path
    return None


def is_archive_mode():
    return archive_path() is not None


def binary_path():
    """The file that is replaced by self-update: the archive, else the entry script."""
    archive = archive_path()
    if archive:
        return os.path.realpath(archive)
    if os.path.isfile(ENTRY_SCRIPT):
        return os.path.realpath(ENTRY_SCRIPT)
    return os.path.realpath(sys.argv[0]) if sys.argv and sys.argv[0] else None


def is_binary_writable(path=None):
    path = path or binary_path()
    if not path or not os.path.isfile(path):
        return False
    return os.access(path, os.W_OK) and os.access(os.path.dirname(path) or ".", os.W_OK)


# -- runtime binary ----------------------------------------------------------------


def runtime_binary(environ=None):
    """``APPCTL_RUNTIME_BIN``, ``APPCTL_RUNTIME_BIN_USED``, the running interpreter, ``python3``."""
    environ = os.environ if environ is None else environ
    for name in (RUNTIME_BIN_ENV, RUNTIME_BIN_USED_ENV):
        value = environ.get(name)
        if value and str(value).strip():
            return str(value).strip()
    if sys.executable:
        return sys.executable
    return FALLBACK_RUNTIME


def runtime_binary_path(environ=None):
    """Absolute path of the runtime binary, when it can be found."""
    binary = runtime_binary(environ)
    if os.path.isabs(binary):
        return binary
    found = shutil.which(binary)
    return os.path.abspath(found) if found else None


def _is_running_interpreter(binary):
    if not sys.executable:
        return False
    try:
        return os.path.realpath(binary) == os.path.realpath(sys.executable)
    except OSError:
        return False


def runtime_version(environ=None):
    """Version of the runtime binary; the running interpreter's when it cannot be queried."""
    binary = runtime_binary(environ)
    if _is_running_interpreter(binary) or not (os.path.isabs(binary) or shutil.which(binary)):
        return platform.python_version()
    try:
        completed = subprocess.run([binary, "--version"], capture_output=True, text=True,
                                   timeout=RUNTIME_CHECK_TIMEOUT, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return platform.python_version()
    match = _VERSION_RE.search(completed.stdout + " " + completed.stderr)
    if completed.returncode != 0 or not match:
        return platform.python_version()
    return match.group(0)


# -- requirements ------------------------------------------------------------------


def runtime_responsive(output=None, attempts=RUNTIME_CHECK_ATTEMPTS,
                       backoff=RUNTIME_CHECK_BACKOFF, sleep=None):
    """Probe the container runtime, retrying with exponential backoff."""
    sleep = sleep or time.sleep
    delay = backoff
    for attempt in range(1, attempts + 1):
        result = run_command([container.RUNTIME_BINARY, "ps", "-q"], output,
                             timeout=RUNTIME_CHECK_TIMEOUT)
        if result.succeeded:
            return True
        if attempt < attempts:
            if output is not None:
                output.debug(f"Container runtime check failed (attempt {attempt} of {attempts}),"
                             f" retrying in {delay:g}s.", group="bootstrap")
            sleep(delay)
            delay *= 2
    return False


def runtime_error(platform_name=None):
    hint = RUNTIME_DARWIN_HINT if is_darwin(platform_name) else RUNTIME_LINUX_HINT
    return f"{RUNTIME_DOWN} {hint}"


def compose_errors(output=None):
    container._compose_binary.clear()
    try:
        binary = container.compose_binary(output)
    except AppctlError:
        return [f"{PRODUCT_NAME} requires the compose tool (docker compose or docker-compose)."
                " Please install it."]
    version = compose_version(binary, output)
    if version is None:
        return ["Unable to determine the version of the compose tool."]
    if compare_semver(version, MIN_COMPOSE_VERSION) < 0:
        return [f"{PRODUCT_NAME} requires compose tool version {MIN_COMPOSE_VERSION} or greater"
                f" (installed: {version})."]
    return []


def runtime_version_errors(environ=None):
    version = runtime_version(environ)
    try:
        too_old = compare_semver(version, MIN_RUNTIME_VERSION) < 0
    except ValueError:
        too_old = True
    if too_old:
        return [f"{PRODUCT_NAME} requires {RUNTIME_NAME} {MIN_RUNTIME_VERSION} or greater"
                f" (current: {version})."]
    return []


def requirement_errors(environ=None, output=None, platform_name=None, sleep=None):
    """Every unmet system requirement, as error messages (empty when all are met)."""
    errors = []
    if not runtime_responsive(output, sleep=sleep):
        errors.append(runtime_error(platform_name))
    errors += compose_errors(output)
    errors += runtime_version_errors(environ)
    return errors


def ensure_requirements(environ=None, output=None, platform_name=None, sleep=None):
    """Raise (after reporting every other problem) unless all requirements are met."""
    errors = requirement_errors(environ, output, platform_name, sleep)
    if not errors:
        return True
    for message in errors[:-1]:
        if output is not None:
            output.error(message)
    raise AppctlError(errors[-1])


def requires_system_check(command):
    """Every command outside the ``cli``, ``config`` and ``help`` families."""
    if command is None or command.is_root or not command.path:
        return False
    return command.path[0] not in EXEMPT_FAMILIES
