"""Container runtime integration: compose files, containers, volumes and networks."""

import os
import platform
import re
import shlex
import shutil
import zlib

import yaml

from . import PROGRAM_NAME
from .errors import AppctlError
from .output import Output
from .process import exec_command, run_command

RUNTIME_BINARY = "docker"
LEGACY_COMPOSE_BINARY = "docker-compose"
RUNTIME_MISSING = ("Container runtime is not installed. "
                   "Please install the container runtime to run AppCtl.")

RUNNING = "running"
EXITED = "exited"

COMPOSE_EXTENSIONS = (".yml", ".yaml")
BASE_COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
OVERRIDE_COMPOSE_FILES = ("docker-compose.override.yml", "docker-compose.override.yaml",
                          "compose.override.yml", "compose.override.yaml")
CUSTOM_COMPOSE_DIR = "user-docker-compose"

VENDOR_LABEL = f"org.label-schema.vendor={PROGRAM_NAME}"
PROJECT_LABEL_KEY = f"io.{PROGRAM_NAME}.project"
DEFAULT_RUNTIME_ROOT = "/var/lib/docker"

_FALSE_WORDS = ("", "0", "false", "no", "off", "never", "null", "none")


def is_truthy(value):
    """Config values may be booleans, numbers or strings such as ``"false"``."""
    if isinstance(value, str):
        return value.strip().lower() not in _FALSE_WORDS
    return bool(value)


def _output(output):
    return output if output is not None else Output()


def is_darwin(platform_name=None):
    return (platform_name or platform.system()).lower() == "darwin"


# -- naming --------------------------------------------------------------------


def project_prefix(name):
    """Deterministic, runtime-safe prefix for every resource of project ``name``.

    Lowercase alphanumerics are kept, everything else is dropped. A name with
    no usable character gets a stable checksum-based prefix instead.
    """
    text = str(name).strip().lower()
    prefix = re.sub(r"[^a-z0-9]", "", text)
    if not prefix:
        prefix = f"{PROGRAM_NAME}{zlib.crc32(text.encode('utf-8')):08x}"
    return prefix


def volume_name(prefix, name):
    return f"{prefix}_{name}"


# -- compose files -------------------------------------------------------------


def is_compose_file(path):
    """A readable ``.yml``/``.yaml`` file whose content is a YAML mapping (or empty)."""
    if not os.path.isfile(path) or not path.lower().endswith(COMPOSE_EXTENSIONS):
        return False
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return False
    return data is None or isinstance(data, dict)


def find_base_compose_file(directory, search_parents=False):
    """The project's base compose file in ``directory`` (optionally searching upward)."""
    directory = os.path.abspath(directory)
    while True:
        for name in BASE_COMPOSE_FILES:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
        parent = os.path.dirname(directory)
        if not search_parents or parent == directory:
            return None
        directory = parent


def _resolve_custom(path, base_dirs):
    path = os.path.expanduser(str(path))
    if os.path.isabs(path):
        return path if os.path.exists(path) else None
    for base in base_dirs:
        if base:
            candidate = os.path.join(base, path)
            if os.path.exists(candidate):
                return os.path.abspath(candidate)
    return None


def discovered_overrides(project_dir):
    """Optional overrides from the project layout, in a deterministic order.

    The standard override files come first, then the files of the
    ``user-docker-compose`` directory sorted by name.
    """
    found = []
    for name in OVERRIDE_COMPOSE_FILES:
        candidate = os.path.join(project_dir, name)
        if is_compose_file(candidate):
            found.append(candidate)
    custom_dir = os.path.join(project_dir, CUSTOM_COMPOSE_DIR)
    if os.path.isdir(custom_dir):
        for name in sorted(os.listdir(custom_dir)):
            candidate = os.path.join(custom_dir, name)
            if is_compose_file(candidate):
                found.append(candidate)
    return found


def compose_files(project_dir, custom_compose=None, output=None, base_dirs=None,
                  search_parents=False):
    """Ordered compose files for ``project_dir``: the base file, then overrides.

    A non-empty ``custom_compose`` replaces the discovered overrides; when it
    does not exist a warning is shown and only the base file is used.
    Relative custom paths are looked up in ``base_dirs`` (default: the
    current directory, then the project directory).
    """
    project_dir = os.path.abspath(project_dir)
    files = []
    base = find_base_compose_file(project_dir, search_parents)
    if base:
        files.append(base)
        project_dir = os.path.dirname(base)
    if custom_compose not in (None, "", False) and str(custom_compose).strip():
        if base_dirs is None:
            base_dirs = [os.getcwd(), project_dir]
        resolved = _resolve_custom(custom_compose, base_dirs)
        if resolved is None:
            _output(output).warning(
                f"File: {custom_compose} does not exist. Falling back to default compose file."
            )
        elif is_compose_file(resolved) and resolved not in files:
            files.append(resolved)
    else:
        files.extend(f for f in discovered_overrides(project_dir) if f not in files)
    return files


def _merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _merge(base[key], value) if key in base else value
        return merged
    return override


def load_compose_config(files):
    """Merge the compose files in order; later files win."""
    merged = {}
    for path in files:
        try:
            with open(path, encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except OSError as exc:
            raise AppctlError(f"Unable to read the compose file '{path}': "
                              f"{exc.strerror or exc}.") from exc
        except yaml.YAMLError as exc:
            raise AppctlError(f"Unable to parse the compose file '{path}': {exc}") from exc
        if data is None:
            continue
        if not isinstance(data, dict):
            raise AppctlError(f"The compose file '{path}' must contain a YAML mapping.")
        merged = _merge(merged, data)
    return merged


def compose_services(config):
    services = (config or {}).get("services")
    if not isinstance(services, dict):
        return []
    return [str(name) for name in services]


def project_services(project_dir, custom_compose=None, output=None):
    return compose_services(load_compose_config(
        compose_files(project_dir, custom_compose, output)))


def service_exists(service, project_dir, custom_compose=None, output=None):
    """Whether ``service`` is defined in the project's compose configuration."""
    if not project_dir or not os.path.isdir(project_dir):
        return False
    return str(service) in project_services(project_dir, custom_compose, output)


# -- runtime binaries ------------------------------------------------------------


def ensure_runtime_installed():
    if shutil.which(RUNTIME_BINARY) is None:
        raise AppctlError(RUNTIME_MISSING)


_compose_binary = {}


def compose_binary(output=None):
    """argv prefix of the compose tool (``docker compose`` or ``docker-compose``)."""
    key = os.environ.get("PATH", "")
    if key not in _compose_binary:
        if shutil.which(RUNTIME_BINARY) and exec_command(
                [RUNTIME_BINARY, "compose", "version"], output):
            _compose_binary[key] = [RUNTIME_BINARY, "compose"]
        elif shutil.which(LEGACY_COMPOSE_BINARY):
            _compose_binary[key] = [LEGACY_COMPOSE_BINARY]
        else:
            raise AppctlError(RUNTIME_MISSING)
    return list(_compose_binary[key])


def compose_command(project_dir, runtime=None, output=None, project=None):
    """Compose argv prefix with every merged compose file and the project name."""
    runtime = runtime or {}
    files = compose_files(project_dir, runtime.get("custom-compose"), output)
    argv = compose_binary(output)
    for path in files:
        argv += ["-f", path]
    if project:
        argv += ["-p", project_prefix(project)]
    return argv


# -- containers -------------------------------------------------------------------


def container_status(container, output=None):
    """``"running"``, ``"exited"`` or ``None`` when the container does not exist."""
    ensure_runtime_installed()
    result = run_command([RUNTIME_BINARY, "inspect", "--type", "container",
                          "-f", "{{.State.Running}}", str(container)], output)
    if not result.succeeded:
        return None
    return RUNNING if result.stdout.strip().lower() == "true" else EXITED


def start_container(container, output=None):
    return exec_command([RUNTIME_BINARY, "start", str(container)], output)


def stop_container(container, output=None):
    return exec_command([RUNTIME_BINARY, "stop", str(container)], output)


def restart_container(container, output=None):
    return exec_command([RUNTIME_BINARY, "restart", str(container)], output)


def create_container(container, command=None, output=None):
    """Create and start ``container``.

    ``command`` holds the extra ``docker run`` arguments (a string or a list);
    the container runs detached under the given name.
    """
    if isinstance(command, str):
        command = shlex.split(command)
    argv = [RUNTIME_BINARY, "run", "-d", "--name", str(container)] + list(command or [])
    return exec_command(argv, output)


def boot_container(container, command=None, output=None):
    """Ensure ``container`` runs: start it if exited, create it if missing."""
    status = container_status(container, output)
    if status == EXITED:
        return start_container(container, output)
    if status == RUNNING:
        return True
    return create_container(container, command, output)


# -- compose services ---------------------------------------------------------------


def compose_up(project_dir, services=(), runtime=None, output=None, project=None):
    """Start the project's services (all, or only ``services``) in detached mode."""
    argv = compose_command(project_dir, runtime, output, project) + ["up", "-d"]
    argv += [str(s) for s in services or ()]
    return exec_command(argv, output, cwd=project_dir)


def compose_down(project_dir, runtime=None, output=None, project=None):
    """Remove every container, network and volume of the compose project."""
    argv = compose_command(project_dir, runtime, output, project) + [
        "down", "--volumes", "--remove-orphans"]
    return exec_command(argv, output, cwd=project_dir)


def compose_exec_command(project_dir, service, command, runtime=None, output=None,
                         user=None, shell="sh", shell_wrapper=True, project=None):
    """argv running ``command`` inside the running ``service`` container."""
    runtime = runtime or {}
    argv = compose_command(project_dir, runtime, output, project) + ["exec"]
    if is_truthy(runtime.get("skip-tty")):
        argv.append("-T")
    if user:
        argv += ["--user", str(user)]
    argv.append(str(service))
    if shell_wrapper:
        if not isinstance(command, str):
            command = shlex.join(str(part) for part in command)
        argv += [shell or "sh", "-c", command]
    else:
        argv += shlex.split(command) if isinstance(command, str) else [str(p) for p in command]
    return argv


def compose_exec(project_dir, service, command, runtime=None, output=None, user=None,
                 shell="sh", shell_wrapper=True, project=None):
    argv = compose_exec_command(project_dir, service, command, runtime, output, user, shell,
                                shell_wrapper, project)
    return run_command(argv, output, cwd=project_dir)


# -- volumes ---------------------------------------------------------------------------


def volume_exists(name, output=None):
    return exec_command([RUNTIME_BINARY, "volume", "inspect", str(name)], output)


def runtime_root_dir(output=None):
    result = run_command([RUNTIME_BINARY, "info", "-f", "{{.DockerRootDir}}"], output)
    root = result.stdout.strip() if result.succeeded else ""
    return root or DEFAULT_RUNTIME_ROOT


def _symlink(target, link):
    directory = os.path.dirname(link)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if os.path.islink(link):
        if os.readlink(link) == target:
            return
        os.unlink(link)
    elif os.path.exists(link):
        return
    os.symlink(target, link)


def create_volumes(prefix, volumes, output=None, platform_name=None, update_runtime=True):
    """Create the project's persistent volumes; return the names created.

    Each specification has ``name``, ``path_to_symlink`` and optionally
    ``skip_volume``, ``skip_linux`` and ``skip_darwin``. Existing volumes are
    skipped silently. On Linux the volume data is symlinked to
    ``path_to_symlink``; elsewhere only its parent directory is created.
    """
    created = []
    darwin = is_darwin(platform_name)
    root = None
    for volume in volumes or ():
        if volume.get("skip_volume") is True:
            continue
        name = volume_name(prefix, volume["name"])
        if volume_exists(name, output):
            continue
        link = volume.get("path_to_symlink")
        if link:
            os.makedirs(os.path.dirname(os.path.abspath(link)), exist_ok=True)
        if update_runtime:
            argv = [RUNTIME_BINARY, "volume", "create",
                    "--label", VENDOR_LABEL,
                    "--label", f"{PROJECT_LABEL_KEY}={prefix}",
                    name]
            if not exec_command(argv, output):
                raise AppctlError(f"There was some error creating the volume '{name}'.")
        created.append(name)
        if link and not darwin and not volume.get("skip_linux"):
            if root is None:
                root = runtime_root_dir(output)
            try:
                _symlink(os.path.join(root, "volumes", name, "_data"), link)
            except OSError as exc:
                _output(output).warning(
                    f"Unable to link the volume '{name}' to '{link}': {exc.strerror or exc}.")
    return created


def mounting_volume_array(volumes, platform_name=None):
    """Compose ``volumes:`` entries for the current platform.

    Darwin mounts the host path (``path_to_symlink``), Linux the named volume.
    """
    darwin = is_darwin(platform_name)
    mounts = []
    for volume in volumes or ():
        if darwin:
            if not volume.get("skip_darwin"):
                mounts.append(f"{volume['path_to_symlink']}:{volume['container_path']}")
        elif not volume.get("skip_linux"):
            mounts.append(f"{volume['name']}:{volume['container_path']}")
    return mounts


# -- networks -----------------------------------------------------------------------------


def create_network(name, output=None, project=None):
    argv = [RUNTIME_BINARY, "network", "create", "--label", VENDOR_LABEL]
    if project:
        argv += ["--label", f"{PROJECT_LABEL_KEY}={project}"]
    return exec_command(argv + [str(name)], output)


def connect_network(network, container, output=None):
    """Connect ``network`` to ``container``; raise on failure."""
    if not exec_command([RUNTIME_BINARY, "network", "connect", str(network), str(container)],
                        output):
        raise AppctlError(f"There was some error connecting to {container}.")
    _output(output).success(f"Project connected to {container}.")
    return True


def disconnect_network(network, container, output=None):
    """Disconnect ``network`` from ``container``; failures only warn."""
    output = _output(output)
    if exec_command([RUNTIME_BINARY, "network", "disconnect", str(network), str(container)],
                    output):
        output.log(f"[{network}] Disconnected from Docker network of {container}")
        return True
    output.warning(f"Error in disconnecting from Docker network of {container}")
    return False


def remove_network(name, output=None):
    return exec_command([RUNTIME_BINARY, "network", "rm", str(name)], output)


def network_exists(name, output=None):
    return exec_command([RUNTIME_BINARY, "network", "inspect", str(name)], output)


# -- project creation ---------------------------------------------------------------------


def create_project(name, volumes=(), output=None, platform_name=None):
    """Create the network and persistent volumes of project ``name``."""
    prefix = project_prefix(name)
    if not network_exists(prefix, output) and not create_network(prefix, output, prefix):
        raise AppctlError(f"There was some error creating the network '{prefix}'.")
    create_volumes(prefix, volumes, output, platform_name)
    return prefix
