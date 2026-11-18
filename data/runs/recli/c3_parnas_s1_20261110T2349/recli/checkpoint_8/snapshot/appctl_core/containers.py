"""Containers, compose projects, volumes and networks.

Secret: which container runtime binary is driven and with which arguments,
how compose files are discovered and merged, how project-scoped resource
names are derived, which labels mark resources as belonging to appctl, and
how volumes are linked into the host filesystem on each platform.
"""

import glob
import os
import re
import shlex
import shutil
import subprocess
import sys

from . import messages as _messages
from . import process, yaml_lite
from .errors import CliError
from .output import Output

RUNTIME = "docker"
RUNNING = "running"
EXITED = "exited"
VENDOR_LABEL = "org.label-schema.vendor=AppCtl"
PROJECT_LABEL = "io.appctl.project"
DEFAULT_ROOT_DIR = "/var/lib/docker"

# Base compose file names, in order of preference.
BASE_COMPOSE_FILES = ("compose.yaml", "compose.yml",
                      "docker-compose.yaml", "docker-compose.yml")
# Optional overrides discovered in a project directory, in order of application.
OVERRIDE_COMPOSE_FILES = ("compose.override.yaml", "compose.override.yml",
                          "docker-compose.override.yaml", "docker-compose.override.yml",
                          "docker-compose-custom.yaml", "docker-compose-custom.yml")
OVERRIDE_COMPOSE_DIR = "user-docker-compose"
_COMPOSE_EXTENSIONS = (".yml", ".yaml")
# Service keys whose sequence value is replaced, not extended, by an override.
_REPLACED_KEYS = {"command", "entrypoint", "test", "dns", "dns_search"}
_FALSE_WORDS = {"", "0", "false", "no", "off", "none", "null"}


# --- naming -------------------------------------------------------------------

def project_prefix(project):
    """Deterministic, runtime-safe prefix for resources of ``project``."""
    return re.sub(r"[^a-z0-9]", "", str(project).lower())


def volume_name(project, volume):
    """Name of the persistent volume ``volume`` (a spec or a name) of ``project``."""
    name = volume["name"] if isinstance(volume, dict) else volume
    return f"{project_prefix(project)}_{name}"


def project_labels(project):
    return [VENDOR_LABEL, f"{PROJECT_LABEL}={project}"]


def is_truthy(value):
    if isinstance(value, str):
        return value.strip().lower() not in _FALSE_WORDS
    return bool(value)


def is_darwin(platform=None):
    return (platform or sys.platform) == "darwin"


# --- compose files ------------------------------------------------------------

def is_compose_file(path):
    return os.path.isfile(path) and path.lower().endswith(_COMPOSE_EXTENSIONS)


def base_compose_file(project_dir):
    for name in BASE_COMPOSE_FILES:
        candidate = os.path.join(project_dir, name)
        if is_compose_file(candidate):
            return candidate
    return None


def discovered_overrides(project_dir):
    """Optional override files found in ``project_dir``, in application order."""
    found = [os.path.join(project_dir, name) for name in OVERRIDE_COMPOSE_FILES]
    found = [path for path in found if is_compose_file(path)]
    pattern = os.path.join(glob.escape(os.path.join(project_dir, OVERRIDE_COMPOSE_DIR)), "*")
    found += sorted(path for path in glob.glob(pattern) if is_compose_file(path))
    return found


def _resolve_custom(custom, cwd, project_dir):
    path = os.path.expanduser(str(custom))
    if os.path.isabs(path):
        return path
    for base in (cwd, project_dir):
        candidate = os.path.join(base, path)
        if os.path.exists(candidate):
            return os.path.normpath(candidate)
    return os.path.normpath(os.path.join(cwd, path))


def compose_files(project_dir, custom=None, cwd=None, out=None):
    """The compose files of a project: the base file, then the overrides.

    A non-empty ``custom`` path is applied after the base file; otherwise
    overrides are discovered in the project directory. A missing custom file
    is reported as a warning and skipped.
    """
    project_dir = os.path.abspath(project_dir)
    files = []
    base = base_compose_file(project_dir)
    if base:
        files.append(base)
    if custom not in (None, "") and str(custom).strip():
        path = _resolve_custom(custom, cwd or project_dir, project_dir)
        if not os.path.isfile(path):
            (out or _default_output()).warning(_messages.custom_compose_missing(custom))
        elif is_compose_file(path) and path not in files:
            files.append(path)
    else:
        files += [path for path in discovered_overrides(project_dir) if path not in files]
    return files


def _merge_sequence(old, new):
    merged = list(old)
    for item in new:
        if item not in merged:
            merged.append(item)
    return merged


def merge_compose(base, override, key=None):
    """Merge one compose definition into another, as compose does."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for name, value in override.items():
            merged[name] = (merge_compose(merged[name], value, name)
                            if name in merged else value)
        return merged
    if (isinstance(base, list) and isinstance(override, list)
            and key not in _REPLACED_KEYS):
        return _merge_sequence(base, override)
    return override


def load_compose(files):
    """Merged compose definition of ``files``."""
    merged = {}
    for path in files:
        try:
            with open(path, encoding="utf-8") as handle:
                data = yaml_lite.load(handle.read())
        except OSError as exc:
            raise CliError(_messages.compose_unparsable(path, exc)) from None
        except yaml_lite.YamlError as exc:
            raise CliError(_messages.compose_unparsable(path, exc)) from None
        if isinstance(data, dict):
            merged = merge_compose(merged, data)
    return merged


def service_names(definition):
    services = definition.get("services") if isinstance(definition, dict) else None
    return [str(name) for name in services] if isinstance(services, dict) else []


# --- runtime ------------------------------------------------------------------

def _default_output():
    return Output(sys.stdout, sys.stderr)


def _fileno(stream):
    try:
        return stream.fileno()
    except (AttributeError, OSError, ValueError):
        return None


class Runtime:
    """Drives the container runtime on behalf of one invocation.

    ``config`` is anything with a ``get(name, default)`` method (e.g. the
    effective runtime configuration); ``custom-compose`` and ``skip-tty`` are
    read from it.
    """

    def __init__(self, out=None, env=None, cwd=None, config=None, platform=None,
                 stdout=None, stderr=None):
        self.out = out or _default_output()
        self.env = dict(env) if env is not None else dict(os.environ)
        self.cwd = cwd or os.getcwd()
        self.config = config if config is not None else {}
        self.platform = platform
        self.stdout = stdout
        self.stderr = stderr

    # --- plumbing -----------------------------------------------------------

    def _setting(self, name):
        return self.config.get(name, None)

    def is_installed(self):
        return shutil.which(RUNTIME, path=self.env.get("PATH")) is not None

    def ensure_installed(self):
        if not self.is_installed():
            raise CliError(_messages.container_runtime_missing())

    def run(self, args, cwd=None):
        """Run the runtime with ``args``; return the ``ProcessRun``."""
        self.ensure_installed()
        return process.run([RUNTIME] + [str(a) for a in args], cwd=cwd or self.cwd,
                           env=self.env, out=self.out)

    def check(self, args, cwd=None):
        return self.run(args, cwd=cwd).succeeded

    def passthrough(self, args, cwd=None):
        """Run the runtime attached to the terminal; return its exit code."""
        self.ensure_installed()
        argv = [RUNTIME] + [str(a) for a in args]
        self.out.debug(f"Running command: {process.command_text(argv)}", group="process")
        stdout = self.stdout if self.stdout is not None else self.out.stdout
        stderr = self.stderr if self.stderr is not None else self.out.stderr
        for stream in (stdout, stderr):
            if hasattr(stream, "flush"):
                stream.flush()
        out_fd, err_fd = _fileno(stdout), _fileno(stderr)
        try:
            proc = subprocess.run(
                argv, cwd=cwd or self.cwd, env=self.env,
                stdout=out_fd if out_fd is not None else subprocess.PIPE,
                stderr=err_fd if err_fd is not None else subprocess.PIPE)
        except OSError as exc:
            stderr.write(f"{getattr(exc, 'strerror', None) or exc}\n")
            return 127
        if out_fd is None and proc.stdout:
            stdout.write(proc.stdout.decode(errors="replace"))
        if err_fd is None and proc.stderr:
            stderr.write(proc.stderr.decode(errors="replace"))
        return proc.returncode

    # --- containers ---------------------------------------------------------

    def container_status(self, container):
        """``"running"``, ``"exited"`` or ``None`` when there is no such container."""
        result = self.run(["inspect", "--type=container", "-f", "{{.State.Running}}",
                           container])
        if not result.succeeded:
            return None
        return RUNNING if result.stdout.strip().lower() == "true" else EXITED

    def start_container(self, container):
        return self.check(["start", container])

    def stop_container(self, container):
        return self.check(["stop", container])

    def restart_container(self, container):
        return self.check(["restart", container])

    def boot_container(self, container, create=None):
        """Make sure ``container`` runs: start it if exited, create it if
        missing. ``create`` is a callable, a runtime argument list, or a shell
        command string."""
        status = self.container_status(container)
        if status == EXITED:
            return self.start_container(container)
        if status == RUNNING:
            return True
        if create is None:
            return False
        if callable(create):
            return bool(create())
        if isinstance(create, str):
            return process.run(create, cwd=self.cwd, env=self.env, out=self.out).succeeded
        return self.check(create)

    # --- compose ------------------------------------------------------------

    def compose_files(self, project_dir):
        return compose_files(project_dir, self._setting("custom-compose"),
                             cwd=self.cwd, out=self.out)

    def compose_args(self, project_dir, files=None):
        """Runtime arguments selecting the merged compose project."""
        project_dir = os.path.abspath(project_dir)
        if files is None:
            files = self.compose_files(project_dir)
        args = ["compose"]
        prefix = project_prefix(os.path.basename(project_dir))
        if prefix:
            args += ["-p", prefix]
        for path in files:
            args += ["-f", path]
        return args

    def compose_definition(self, project_dir):
        files = self.compose_files(project_dir)
        if not files:
            raise CliError(_messages.no_compose_file(os.path.abspath(project_dir)))
        return load_compose(files)

    def services(self, project_dir):
        """Service names, in the order they appear in the merged configuration."""
        return service_names(self.compose_definition(project_dir))

    def service_exists(self, project_dir, service):
        try:
            return str(service) in self.services(project_dir)
        except CliError:
            return False

    def compose_up(self, project_dir, services=(), no_deps=False):
        args = self.compose_args(project_dir) + ["up", "-d"]
        if no_deps:
            args.append("--no-deps")
        args += [str(s) for s in services or ()]
        return self.run(args, cwd=os.path.abspath(project_dir))

    def compose_stop(self, project_dir, services=()):
        args = self.compose_args(project_dir) + ["stop"] + [str(s) for s in services or ()]
        return self.run(args, cwd=os.path.abspath(project_dir))

    def compose_rm(self, project_dir, services=()):
        """Remove the stopped containers of ``services`` (all when empty)."""
        args = self.compose_args(project_dir) + ["rm", "-f"] + [str(s) for s in services or ()]
        return self.run(args, cwd=os.path.abspath(project_dir))

    def compose_version(self):
        """Raw output of the compose tool's version command (``None`` when
        it fails)."""
        result = self.run(["compose", "version", "--short"])
        return result.stdout.strip() if result.succeeded else None

    def compose_down(self, project_dir):
        args = self.compose_args(project_dir) + ["down", "--volumes", "--remove-orphans"]
        return self.run(args, cwd=os.path.abspath(project_dir))

    def exec_args(self, project_dir, service, command, user=None, shell="sh",
                  shell_wrapper=False):
        args = self.compose_args(project_dir) + ["exec"]
        if is_truthy(self._setting("skip-tty")):
            args.append("-T")
        if user:
            args.append(f"--user={user}")
        args.append(str(service))
        if shell_wrapper:
            text = command if isinstance(command, str) else process.command_text(command)
            return args + [shell or "sh", "-c", text]
        if isinstance(command, str):
            return args + shlex.split(command)
        return args + [str(part) for part in command]

    def compose_exec(self, project_dir, service, command, user=None, shell="sh",
                     shell_wrapper=False, interactive=False):
        """Run ``command`` in the container of ``service``. Returns the exit
        code when ``interactive`` (attached to the terminal), otherwise the
        ``ProcessRun``."""
        args = self.exec_args(project_dir, service, command, user=user, shell=shell,
                              shell_wrapper=shell_wrapper)
        cwd = os.path.abspath(project_dir)
        if interactive:
            return self.passthrough(args, cwd=cwd)
        return self.run(args, cwd=cwd)

    # --- images -------------------------------------------------------------

    def image_references(self):
        """Local images as ``repository:tag`` strings (``None`` on failure)."""
        result = self.run(["image", "ls", "--format", "{{.Repository}}:{{.Tag}}"])
        if not result.succeeded:
            return None
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def pull_image(self, image):
        return self.run(["pull", image])

    def remove_image(self, image):
        return self.run(["image", "rm", image])

    def prune_images(self):
        """Remove unused appctl images."""
        return self.run(["image", "prune", "--all", "--force",
                         "--filter", f"label={VENDOR_LABEL}"])

    def prune_networks(self):
        """Remove unused appctl networks."""
        return self.run(["network", "prune", "--force", "--filter", f"label={VENDOR_LABEL}"])

    # --- volumes ------------------------------------------------------------

    def root_dir(self):
        result = self.run(["info", "--format", "{{.DockerRootDir}}"])
        root = result.stdout.strip() if result.succeeded else ""
        return root or DEFAULT_ROOT_DIR

    def volume_exists(self, name):
        return self.check(["volume", "inspect", name])

    def create_volumes(self, project, volumes):
        """Create the persistent volumes of ``project``; return the names of
        the volumes that were created."""
        created = []
        darwin = is_darwin(self.platform)
        root = None
        for volume in volumes or ():
            if volume.get("skip_volume") is True:
                continue
            name = volume_name(project, volume)
            if self.volume_exists(name):
                continue
            labels = []
            for label in project_labels(project):
                labels += ["--label", label]
            result = self.run(["volume", "create"] + labels + [name])
            if not result.succeeded:
                raise CliError(result.stderr.strip() or f"Unable to create volume '{name}'.")
            created.append(name)
            link = volume.get("path_to_symlink")
            if not link:
                continue
            if darwin:
                if not volume.get("skip_darwin"):
                    os.makedirs(link, exist_ok=True)
            elif not volume.get("skip_linux"):
                if root is None:
                    root = self.root_dir()
                parent = os.path.dirname(link)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                if not os.path.lexists(link):
                    os.symlink(os.path.join(root, "volumes", name, "_data"), link)
        return created

    def mounting_volumes(self, volumes):
        return mounting_volumes(volumes, self.platform)

    # --- networks -----------------------------------------------------------

    def create_network(self, project, name=None):
        args = ["network", "create"]
        for label in project_labels(project):
            args += ["--label", label]
        return self.check(args + [name or project])

    def connect_network(self, network, container):
        if not self.check(["network", "connect", network, container]):
            raise CliError(_messages.network_connect_failed(container))
        self.out.success(_messages.network_connected(container))
        return True

    def disconnect_network(self, network, container):
        if self.check(["network", "disconnect", network, container]):
            self.out.log(_messages.network_disconnected(network, container))
            return True
        self.out.warning(_messages.network_disconnect_failed(container))
        return False

    def remove_network(self, name):
        return self.check(["network", "rm", name])

    def network_exists(self, name):
        return self.check(["network", "inspect", name])


def split_image(image):
    """``(repository, tag)`` of an image reference; the tag is ``None`` when
    absent (a digest is kept as the tag, with its ``@``)."""
    image = str(image).strip()
    if "@" in image:
        repository, digest = image.split("@", 1)
        return repository, "@" + digest
    slash = image.rfind("/")
    colon = image.rfind(":")
    if colon > slash:
        return image[:colon], image[colon + 1:]
    return image, None


def mounting_volumes(volumes, platform=None):
    """Compose mount entries (``source:container_path``) for ``volumes`` on
    the current platform, omitting volumes skipped for it."""
    darwin = is_darwin(platform)
    mounts = []
    for volume in volumes or ():
        if darwin and volume.get("skip_darwin"):
            continue
        if not darwin and volume.get("skip_linux"):
            continue
        source = volume["name"]
        if darwin and volume.get("path_to_symlink"):
            source = volume["path_to_symlink"]
        mounts.append(f"{source}:{volume['container_path']}")
    return mounts
