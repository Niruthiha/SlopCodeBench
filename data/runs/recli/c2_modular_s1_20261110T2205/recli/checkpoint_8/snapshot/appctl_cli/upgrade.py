"""Upgrade orchestration run when the appctl version changes.

The upgrade checks the free disk space, then runs as one revertable
sequence: database migrations, container migrations, image pulls, the
compose tool upgrade, the global and per-project container upgrades and
the persistent state update. When a step fails every completed step is
undone in reverse order. Pruning old images and networks happens last and
never fails the upgrade.
"""

import importlib.util
import inspect
import json
import os
import pkgutil
import platform
import re
import shutil
import stat
import urllib.request
from dataclasses import dataclass

from . import PROGRAM_NAME, __version__, container, database
from .config_loader import packages_dir, root_dir
from .errors import AppctlError
from .output import Output
from .process import exec_command, run_command
from .revertable import RevertableStepProcessor

VERSION_OPTION = "version"
MIGRATION_ERROR = "There was some error while migrating. Please check logs."

MIN_DISK_SPACE = 5 * 1024 ** 3
DISK_SPACE_ERROR = ("Insufficient disk space: minimum 5GB disk space is required to run "
                    "AppCtl. Please free up some disk space and try again.")

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_SOURCE = PROGRAM_NAME
CORE_MIGRATIONS_DIR = os.path.join(PACKAGE_DIR, "migrations")
MIGRATIONS_DIR = "migrations"
DB_MIGRATION = "db"
CONTAINER_MIGRATION = "container"
MIGRATION_TYPES = (DB_MIGRATION, CONTAINER_MIGRATION)
MIGRATION_FILE_RE = re.compile(r"^(\d+)_([A-Za-z0-9][A-Za-z0-9_.\-]*)\.py$")

IMAGE_VERSIONS_FILE = os.path.join(PACKAGE_DIR, "img_versions.json")
GLOBAL_SERVICES_DIR = "services"
GLOBAL_PROJECT = f"{PROGRAM_NAME}-global"

MIN_COMPOSE_VERSION = "2.27.0"
COMPOSE_UPGRADE_VERSION = "2.29.7"
COMPOSE_URL_ENV = "APPCTL_COMPOSE_DOWNLOAD_URL"
COMPOSE_URL = "https://github.com/docker/compose/releases/download/v{version}/docker-compose-{os}-{arch}"
COMPOSE_PLUGIN = "docker-compose"
COMPOSE_PLUGIN_DIRS = ("/usr/local/lib/docker/cli-plugins", "/usr/local/libexec/docker/cli-plugins",
                       "/usr/lib/docker/cli-plugins", "/usr/libexec/docker/cli-plugins")


class ReportedError(AppctlError):
    """A step failure whose details were already shown to the user."""


def _output(output):
    return output if output is not None else Output()


# -- disk space ------------------------------------------------------------------


def _existing_path(path):
    """``path`` or its nearest existing ancestor."""
    path = os.path.abspath(os.path.expanduser(str(path)))
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def check_disk_space(environ=None, output=None):
    """Require 5 GiB free for the appctl root and the container runtime root."""
    environ = os.environ if environ is None else environ
    for path in (root_dir(environ), container.runtime_root_dir(output)):
        try:
            free = shutil.disk_usage(_existing_path(path)).free
        except OSError:
            continue
        if free < MIN_DISK_SPACE:
            raise AppctlError(DISK_SPACE_ERROR)


# -- semantic versions -------------------------------------------------------------

_SEMVER_RE = re.compile(r"v?(\d+(?:\.\d+)*)(?:-([0-9A-Za-z.\-]+))?(?:\+[0-9A-Za-z.\-]+)?")


def parse_semver(text):
    """``(release, prerelease)`` of the first version in ``text``, or ``None``."""
    match = _SEMVER_RE.search(str(text or ""))
    if not match:
        return None
    release = [int(part) for part in match.group(1).split(".")]
    release += [0] * (3 - len(release))
    prerelease = tuple(int(p) if p.isdigit() else p for p in (match.group(2) or "").split(".") if p)
    return tuple(release), prerelease


def _prerelease_key(prerelease):
    # A release sorts after its pre-releases; numeric identifiers before alphanumeric ones.
    if not prerelease:
        return (1,)
    return (0,) + tuple((0, p, "") if isinstance(p, int) else (1, 0, p) for p in prerelease)


def compare_semver(left, right):
    """-1, 0 or 1 as ``left`` is lower than, equal to or greater than ``right``."""
    a, b = parse_semver(left), parse_semver(right)
    if a is None or b is None:
        raise ValueError(f"Invalid version: {left if a is None else right}")
    width = max(len(a[0]), len(b[0]))
    key_a = (a[0] + (0,) * (width - len(a[0])), _prerelease_key(a[1]))
    key_b = (b[0] + (0,) * (width - len(b[0])), _prerelease_key(b[1]))
    return (key_a > key_b) - (key_a < key_b)


# -- migration discovery ------------------------------------------------------------


@dataclass(frozen=True)
class MigrationArtifact:
    source: str
    type: str
    path: str
    sequence: int
    name: str

    @property
    def identity(self):
        """Record name, unique across sources: ``<source>:<file stem>``."""
        return f"{self.source}:{self.name}"

    @property
    def sort_key(self):
        return (self.sequence, self.name, self.source)


def migration_sources(environ=None):
    """``[(source, migrations_dir)]``: appctl first, then extensions by name.

    Extensions live in ``<packages>/<name>`` or ``<packages>/<vendor>/<name>``
    and are identified by that relative path.
    """
    environ = os.environ if environ is None else environ
    sources = [(CORE_SOURCE, CORE_MIGRATIONS_DIR)]
    base = packages_dir(environ)
    if not os.path.isdir(base):
        return sources
    found = []
    for name in sorted(os.listdir(base)):
        directory = os.path.join(base, name)
        if not os.path.isdir(directory):
            continue
        if os.path.isdir(os.path.join(directory, MIGRATIONS_DIR)):
            found.append(name)
            continue
        for child in sorted(os.listdir(directory)):
            if os.path.isdir(os.path.join(directory, child, MIGRATIONS_DIR)):
                found.append(f"{name}/{child}")
    for rel in found:
        source = rel if rel != CORE_SOURCE else f"packages/{rel}"
        sources.append((source, os.path.join(base, *rel.split("/"), MIGRATIONS_DIR)))
    return sources


def discover_migrations(type, environ=None):
    """Every migration artifact of ``type``, in ascending migration order."""
    artifacts = []
    for source, directory in migration_sources(environ):
        directory = os.path.join(directory, type)
        if not os.path.isdir(directory):
            continue
        for filename in sorted(os.listdir(directory)):
            match = MIGRATION_FILE_RE.match(filename)
            path = os.path.join(directory, filename)
            if match and os.path.isfile(path):
                artifacts.append(MigrationArtifact(source, type, path, int(match.group(1)),
                                                   filename[:-len(".py")]))
    return sorted(artifacts, key=lambda a: a.sort_key)


def pending_migrations(db, type, environ=None):
    """Discovered migrations of ``type`` not yet in the migration history."""
    applied = set(db.get_migration_names(type))
    return [a for a in discover_migrations(type, environ) if a.identity not in applied]


# -- migration execution ---------------------------------------------------------------


class MigrationFileNotFound(AppctlError):
    def __init__(self, path):
        super().__init__(f"Migration file not found: {path}")
        self.path = path


@dataclass
class MigrationContext:
    """What a migration's ``up()``/``down()`` receive."""

    db: object
    output: object
    environ: object
    artifact: MigrationArtifact

    @property
    def root_dir(self):
        return root_dir(self.environ)

    @property
    def source(self):
        return self.artifact.source

    @property
    def name(self):
        return self.artifact.name

    @property
    def type(self):
        return self.artifact.type

    @property
    def path(self):
        return self.artifact.path


def _module_name(artifact):
    return "appctl_migration_" + re.sub(r"\W", "_", f"{artifact.type}_{artifact.source}_"
                                                      f"{artifact.name}")


def load_migration(artifact):
    """``(up, down)`` callables of the migration file found by its source."""
    if not os.path.isfile(artifact.path):
        raise MigrationFileNotFound(artifact.path)
    spec = importlib.util.spec_from_file_location(_module_name(artifact), artifact.path)
    if spec is None or spec.loader is None:
        raise MigrationFileNotFound(artifact.path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except FileNotFoundError as exc:
        raise MigrationFileNotFound(artifact.path) from exc
    target = module
    if inspect.isclass(getattr(module, "Migration", None)):
        target = module.Migration()
    up, down = getattr(target, "up", None), getattr(target, "down", None)
    if not callable(up):
        raise AppctlError(f"Migration '{artifact.identity}' does not define up().")
    return up, down if callable(down) else None


def _call(function, context):
    try:
        parameters = inspect.signature(function).parameters.values()
    except (TypeError, ValueError):
        return function(context)
    accepts = any(p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)
                  for p in parameters)
    return function(context) if accepts else function()


class MigrationBatch:
    """Runs pending migrations of one type; a failure rolls back the batch."""

    def __init__(self, type, db, output=None, environ=None):
        self.type = type
        self.db = db
        self.output = _output(output)
        self.environ = os.environ if environ is None else environ
        self.processor = RevertableStepProcessor(self.output, f"{type} migrations")
        self.applied = []

    def run(self):
        """Apply every pending migration; return the identities that ran."""
        pending = pending_migrations(self.db, self.type, self.environ)
        for artifact in pending:
            state = {}
            self.processor.add_step(artifact.identity, self._up, self._down,
                                    (artifact, state), (artifact, state))
        if self.processor.execute():
            return list(self.applied)
        error = self.processor.error
        if isinstance(error, MigrationFileNotFound):
            self.output.error(error.message)
        else:
            step = self.processor.failed_step
            reason = error.message if isinstance(error, AppctlError) else str(error) or repr(error)
            self.output.error(f"Migration '{step.id}' failed: {reason}")
        raise ReportedError(MIGRATION_ERROR)

    def rollback(self):
        self.processor.rollback()

    def _context(self, artifact):
        return MigrationContext(self.db, self.output, self.environ, artifact)

    def _up(self, artifact, state):
        self.output.debug(f"Running {self.type} migration: {artifact.identity}", group="upgrade")
        up, state["down"] = load_migration(artifact)
        _call(up, self._context(artifact))
        state["done"] = True
        self.db.record_migration(artifact.identity, self.type)
        self.applied.append(artifact.identity)

    def _down(self, artifact, state):
        if not state.pop("done", False):
            return
        self.output.debug(f"Reverting {self.type} migration: {artifact.identity}", group="upgrade")
        try:
            if state.get("down") is not None:
                _call(state["down"], self._context(artifact))
        finally:
            self.db.remove_migration(artifact.identity, self.type)
            if artifact.identity in self.applied:
                self.applied.remove(artifact.identity)


# -- image versions ----------------------------------------------------------------------


def split_image(reference):
    """``(repository, tag)`` of an image reference; the tag may be ``None``."""
    reference = str(reference).split("@", 1)[0]
    slash, colon = reference.rfind("/"), reference.rfind(":")
    if colon > slash:
        return reference[:colon], reference[colon + 1:]
    return reference, None


def target_image_versions(path=None):
    """``{image: tag}`` of the images managed by this appctl version."""
    if path is None and not os.path.isfile(IMAGE_VERSIONS_FILE):
        # Running from an archive: the file is package data, not a real file.
        raw = pkgutil.get_data(__package__, os.path.basename(IMAGE_VERSIONS_FILE))
        data = json.loads(raw.decode("utf-8"))
    else:
        with open(path or IMAGE_VERSIONS_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
    return {str(image): str(tag) for image, tag in sorted(data.items())}


def local_image_tags(output=None):
    """``{repository: {tags}}`` of the images present in the container runtime."""
    result = run_command([container.RUNTIME_BINARY, "images", "--format",
                          "{{.Repository}}:{{.Tag}}"], output)
    tags = {}
    if result.succeeded:
        for line in result.stdout.splitlines():
            repository, tag = split_image(line.strip())
            if repository and tag and tag != "<none>":
                tags.setdefault(repository, set()).add(tag)
    return tags


def current_image_versions(db, targets, output=None):
    """Version in use per image: the recorded one, else the one observed locally."""
    current = {}
    observed = None
    for image, target in targets.items():
        stored = db.get_option(image)
        if stored is not False:
            current[image] = stored
            continue
        if observed is None:
            observed = local_image_tags(output) if shutil.which(container.RUNTIME_BINARY) else {}
        tags = observed.get(image, set())
        current[image] = target if target in tags else (sorted(tags)[-1] if tags else None)
    return current


def changed_images(current, targets):
    """Images whose version differs (exact tag comparison), with their new tag, by name."""
    return {image: tag for image, tag in sorted(targets.items()) if current.get(image) != tag}


def pull_images(changed, output=None):
    """Pull the new images one after the other; stop at the first failure."""
    output = _output(output)
    for image, tag in changed.items():
        reference = f"{image}:{tag}"
        output.debug(f"Pulling image {reference}", group="upgrade")
        if not exec_command([container.RUNTIME_BINARY, "pull", reference], output):
            output.error(f"Unable to pull {reference}. Please check logs for more details.")
            raise ReportedError(MIGRATION_ERROR)


# -- compose projects ------------------------------------------------------------------------

_IMAGE_RE = re.compile(
    r"(?P<pre>\bimage\s*:\s*(?P<q>[\"']?))(?P<ref>[^\s\"'#,{}\[\]]+?)(?P=q)"
    r"(?=\s|,|\}|#|$)", re.MULTILINE)


def affected_services(config, changed):
    """``{service: image repository}`` of the services using a changed image."""
    affected = {}
    for name, service in ((config or {}).get("services") or {}).items():
        image = service.get("image") if isinstance(service, dict) else None
        if image:
            repository, _ = split_image(image)
            if repository in changed:
                affected[str(name)] = repository
    return affected


def rewrite_images(text, changed):
    """Compose file text with every changed image set to its new tag."""
    def replace(match):
        repository, _ = split_image(match.group("ref"))
        if repository not in changed:
            return match.group(0)
        return f"{match.group('pre')}{repository}:{changed[repository]}{match.group('q')}"
    return _IMAGE_RE.sub(replace, text)


class ComposeUpgrade:
    """Revertable replacement of the services of one compose project using changed images."""

    def __init__(self, label, project_dir, project, changed, output=None):
        self.label = label
        self.project_dir = project_dir
        self.project = project
        self.changed = changed
        self.output = _output(output)
        self.files = container.compose_files(project_dir, output=self.output)
        self.services = affected_services(container.load_compose_config(self.files), changed)
        self.originals = {}
        self.processor = RevertableStepProcessor(self.output, label)

    @property
    def needed(self):
        return bool(self.services)

    def run(self):
        self.processor.add_step(f"{self.label}: update compose files", self._rewrite,
                                self._restore_files)
        self.processor.add_step(f"{self.label}: replace containers", self._up,
                                self._restore_containers)
        if not self.processor.execute():
            error = self.processor.error
            reason = error.message if isinstance(error, AppctlError) else str(error)
            self.output.error(f"Unable to upgrade the containers of {self.label}: {reason}")
            raise ReportedError(MIGRATION_ERROR)

    def rollback(self):
        self.processor.rollback()

    def _rewrite(self):
        for path in self.files:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            updated = rewrite_images(text, self.changed)
            if updated != text:
                self.originals[path] = text
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(updated)
        config = container.load_compose_config(self.files)
        for service in self.services:
            image = config["services"][service].get("image")
            repository, tag = split_image(image)
            if tag != self.changed[repository]:
                raise AppctlError(f"Unable to update the image of the '{service}' service.")

    def _restore_files(self):
        for path, text in self.originals.items():
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)

    def _up(self):
        argv = container.compose_command(self.project_dir, output=self.output,
                                         project=self.project)
        argv += ["up", "-d", "--no-deps"] + list(self.services)
        if not exec_command(argv, self.output, cwd=self.project_dir):
            raise AppctlError(f"Unable to start the services: {', '.join(self.services)}.")

    def _restore_containers(self):
        self._restore_files()
        self._up()


def global_services_dir(environ=None):
    environ = os.environ if environ is None else environ
    return os.path.join(root_dir(environ), GLOBAL_SERVICES_DIR)


# -- compose tool ----------------------------------------------------------------------------


def compose_version(binary, output=None):
    """Installed version of the compose tool ``binary`` (an argv prefix), or ``None``."""
    for arguments in (["version", "--short"], ["version"]):
        result = run_command(list(binary) + arguments, output)
        if result.succeeded and parse_semver(result.stdout):
            return _SEMVER_RE.search(result.stdout).group(0).lstrip("v")
    return None


def compose_download_url(version=COMPOSE_UPGRADE_VERSION, environ=None):
    environ = os.environ if environ is None else environ
    template = environ.get(COMPOSE_URL_ENV) or COMPOSE_URL
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    return template.format(version=version, os=platform.system().lower(), arch=arch)


def compose_tool_path(binary, environ=None):
    """File to replace: the legacy binary, or the compose CLI plugin."""
    environ = os.environ if environ is None else environ
    if binary[0] == container.LEGACY_COMPOSE_BINARY:
        found = shutil.which(container.LEGACY_COMPOSE_BINARY)
        return os.path.realpath(found) if found else None
    config_dir = environ.get("DOCKER_CONFIG") or os.path.join(os.path.expanduser("~"), ".docker")
    user_dir = os.path.join(config_dir, "cli-plugins")
    for directory in (user_dir,) + COMPOSE_PLUGIN_DIRS:
        candidate = os.path.join(directory, COMPOSE_PLUGIN)
        if os.path.isfile(candidate):
            return os.path.realpath(candidate)
    return os.path.join(user_dir, COMPOSE_PLUGIN)


def _remove(path):
    if os.path.lexists(path):
        os.unlink(path)


class ComposeToolUpgrade:
    """Replaces a compose tool older than the minimum version, keeping a backup."""

    def __init__(self, output=None, environ=None):
        self.output = _output(output)
        self.environ = os.environ if environ is None else environ
        self.processor = None
        self.path = None
        self.existed = False

    def run(self):
        """Upgrade when needed. Failures restore the old tool and only warn."""
        try:
            binary = container.compose_binary(self.output)
        except AppctlError:
            self.output.debug("No compose tool installed, skipping its upgrade.", group="upgrade")
            return True
        installed = compose_version(binary, self.output)
        if installed is None:
            self.output.debug("Unable to detect the compose tool version.", group="upgrade")
            return True
        if compare_semver(installed, MIN_COMPOSE_VERSION) >= 0:
            return True
        self.path = compose_tool_path(binary, self.environ)
        self.existed = bool(self.path) and os.path.exists(self.path)
        processor = RevertableStepProcessor(self.output, "compose tool upgrade")
        processor.add_step("download compose tool", self._download, self._discard)
        processor.add_step("backup compose tool", self._backup, self._restore)
        processor.add_step("install compose tool", self._install)
        processor.add_step("verify compose tool", self._verify)
        ok = processor.execute()
        container._compose_binary.clear()
        if not ok:
            self.output.warning(
                f"Unable to upgrade the compose tool from version {installed} to "
                f"{COMPOSE_UPGRADE_VERSION}: {processor.error}. Keeping the installed version.")
            return True
        self.processor = processor
        return True

    def rollback(self):
        if self.processor is not None:
            self.processor.rollback()
            self.processor = None
            container._compose_binary.clear()

    def cleanup(self):
        if self.processor is not None and self.path:
            try:
                _remove(self.path + ".backup")
            except OSError:
                pass

    @property
    def _new_path(self):
        return self.path + ".new"

    def _download(self):
        if not self.path:
            raise AppctlError("Unable to locate the compose tool.")
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        url = compose_download_url(environ=self.environ)
        self.output.debug(f"Downloading the compose tool from {url}", group="upgrade")
        with urllib.request.urlopen(url, timeout=120) as response, \
                open(self._new_path, "wb") as handle:
            shutil.copyfileobj(response, handle)
        mode = os.stat(self._new_path).st_mode
        os.chmod(self._new_path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self._check([self._new_path])

    def _discard(self):
        _remove(self._new_path)

    def _backup(self):
        if self.existed:
            shutil.copy2(self.path, self.path + ".backup")

    def _restore(self):
        if self.existed:
            os.replace(self.path + ".backup", self.path)
        else:
            _remove(self.path)

    def _install(self):
        os.replace(self._new_path, self.path)

    def _verify(self):
        container._compose_binary.clear()
        self._check(container.compose_binary(self.output))

    def _check(self, binary):
        version = compose_version(binary, self.output)
        if version is None or compare_semver(version, MIN_COMPOSE_VERSION) < 0:
            raise AppctlError(f"The new compose tool reports version {version or 'unknown'}.")


# -- pruning ---------------------------------------------------------------------------------


def prune_images(targets, output=None):
    """Remove old versions of the managed images and dangling appctl images."""
    output = _output(output)
    ok = True
    tags = local_image_tags(output)
    for image, target in targets.items():
        for tag in sorted(tags.get(image, ())):
            if tag != target:
                ok = exec_command([container.RUNTIME_BINARY, "rmi", f"{image}:{tag}"],
                                  output) and ok
    ok = exec_command([container.RUNTIME_BINARY, "image", "prune", "-f", "--filter",
                       f"label={container.VENDOR_LABEL}"], output) and ok
    if not ok:
        output.warning("Unable to prune some old images.")
    return ok


def prune_networks(output=None):
    """Remove unused appctl networks."""
    output = _output(output)
    ok = exec_command([container.RUNTIME_BINARY, "network", "prune", "-f", "--filter",
                       f"label={container.VENDOR_LABEL}"], output)
    if not ok:
        output.warning("Unable to prune old networks.")
    return ok


# -- orchestration ---------------------------------------------------------------------------


NIGHTLY_MARKER = "nightly"

VERSION_CURRENT = "current"
VERSION_NEWER = "newer"      # the binary is newer than the stored version: migrate
VERSION_OLDER = "older"      # the binary is older than the stored version


def is_nightly(version=__version__):
    return NIGHTLY_MARKER in str(version).lower()


def version_status(stored, current=__version__):
    """How the running binary relates to the stored version.

    Nightly builds always migrate. A stored version that cannot be parsed
    is treated as older than the binary.
    """
    if is_nightly(current):
        return VERSION_NEWER
    try:
        comparison = compare_semver(current, stored)
    except ValueError:
        comparison = 0 if str(stored) == str(current) else 1
    if comparison > 0:
        return VERSION_NEWER
    if comparison < 0:
        return VERSION_OLDER
    return VERSION_CURRENT


def stored_version(db):
    """The persisted appctl version, or ``None`` before the first run."""
    stored = db.get_option(VERSION_OPTION)
    return None if stored is False else stored


def needs_upgrade(db):
    """Whether the stored version calls for a migration of the running binary."""
    stored = stored_version(db)
    return stored is not None and version_status(stored) == VERSION_NEWER


RUNTIME_UNAVAILABLE = ("The container runtime is not available: skipping the image and "
                       "container upgrades.")


def runtime_available(output=None):
    """Whether the container runtime is installed and responds."""
    if not shutil.which(container.RUNTIME_BINARY):
        return False
    return exec_command([container.RUNTIME_BINARY, "ps", "-q"], output)


class Upgrade:
    def __init__(self, environ=None, output=None, db=None, targets=None):
        self.environ = os.environ if environ is None else environ
        self.output = _output(output)
        self.db = db or database.get_db(self.environ)
        self.targets = targets
        self.changed = {}
        self.batches = {}
        self.compose_tool = ComposeToolUpgrade(self.output, self.environ)
        self.global_upgrade = None
        self.project_upgrades = []
        self.previous_state = {}
        self.runtime_available = True

    def run(self):
        check_disk_space(self.environ, self.output)
        if self.targets is None:
            self.targets = target_image_versions()
        self.targets = dict(sorted(self.targets.items()))
        self.runtime_available = runtime_available(self.output)
        processor = RevertableStepProcessor(self.output, "upgrade")
        for type in MIGRATION_TYPES:
            processor.add_step(f"{type} migrations", self._migrate, self._unmigrate,
                               (type,), (type,))
        if self.runtime_available:
            current = current_image_versions(self.db, self.targets, self.output)
            self.changed = changed_images(current, self.targets)
            processor.add_step("pull images", pull_images, None, (self.changed, self.output))
            processor.add_step("compose tool upgrade", self.compose_tool.run,
                               self.compose_tool.rollback)
            processor.add_step("global containers", self._upgrade_global, self._revert_global)
            processor.add_step("project containers", self._upgrade_projects,
                               self._revert_projects)
        else:
            # Images are left unrecorded so they are pulled once the runtime is back.
            self.targets = {}
            self.output.warning(RUNTIME_UNAVAILABLE)
        processor.add_step("save versions", self._save_state, self._restore_state)
        if not processor.execute():
            error = processor.error
            if not isinstance(error, ReportedError):
                reason = error.message if isinstance(error, AppctlError) else str(error)
                self.output.error(f"{processor.failed_step.id} failed: {reason or repr(error)}")
            raise AppctlError(MIGRATION_ERROR)
        self._cleanup()
        return True

    def _migrate(self, type):
        self.batches[type] = MigrationBatch(type, self.db, self.output, self.environ)
        self.batches[type].run()

    def _unmigrate(self, type):
        if type in self.batches:
            self.batches.pop(type).rollback()

    def _upgrade_global(self):
        directory = global_services_dir(self.environ)
        if not self.changed or not container.find_base_compose_file(directory):
            return
        upgrade = ComposeUpgrade("global services", directory, GLOBAL_PROJECT, self.changed,
                                 self.output)
        if upgrade.needed:
            self.global_upgrade = upgrade
            upgrade.run()

    def _revert_global(self):
        if self.global_upgrade is not None:
            self.global_upgrade.rollback()
            self.global_upgrade = None

    def _upgrade_projects(self):
        if not self.changed:
            return
        for project in self.db.get_projects():
            path = project["path"]
            if not os.path.isdir(path) or not container.find_base_compose_file(path):
                self.output.debug(f"Skipping project {project['name']}: no compose file.",
                                  group="upgrade")
                continue
            upgrade = ComposeUpgrade(f"project {project['name']}", path, project["name"],
                                     self.changed, self.output)
            if not upgrade.needed:
                continue
            self.project_upgrades.append(upgrade)
            upgrade.run()

    def _revert_projects(self):
        while self.project_upgrades:
            self.project_upgrades.pop().rollback()

    def _save_state(self):
        keys = list(self.targets) + [VERSION_OPTION]
        self.previous_state = {key: self.db.get_option(key) for key in keys}
        for image, tag in self.targets.items():
            self.db.set_option(image, tag)
        self.db.set_option(VERSION_OPTION, __version__)

    def _restore_state(self):
        for key, value in self.previous_state.items():
            if value is False:
                self.db.delete_option(key)
            else:
                self.db.set_option(key, value)

    def _cleanup(self):
        """Cleanup-only work: its failures never fail the upgrade."""
        self.compose_tool.cleanup()
        if not self.runtime_available or not shutil.which(container.RUNTIME_BINARY):
            return
        for action, args in ((prune_images, (self.targets, self.output)),
                             (prune_networks, (self.output,))):
            try:
                action(*args)
            except Exception as exc:  # pruning is best effort
                self.output.warning(f"Unable to prune: {exc}")


def run_upgrade(environ=None, output=None):
    return Upgrade(environ, output).run()


class Setup:
    """First-run setup: run every pending migration, then record the version."""

    def __init__(self, environ=None, output=None, db=None):
        self.environ = os.environ if environ is None else environ
        self.output = _output(output)
        self.db = db or database.get_db(self.environ)
        self.batches = {}

    def run(self):
        processor = RevertableStepProcessor(self.output, "setup")
        for type in MIGRATION_TYPES:
            processor.add_step(f"{type} migrations", self._migrate, self._unmigrate,
                               (type,), (type,))
        processor.add_step("save version", self.db.set_option, self.db.delete_option,
                           (VERSION_OPTION, __version__), (VERSION_OPTION,))
        if not processor.execute():
            error = processor.error
            if not isinstance(error, ReportedError):
                reason = error.message if isinstance(error, AppctlError) else str(error)
                self.output.error(f"{processor.failed_step.id} failed: {reason or repr(error)}")
            raise AppctlError(MIGRATION_ERROR)
        return True

    def _migrate(self, type):
        self.batches[type] = MigrationBatch(type, self.db, self.output, self.environ)
        self.batches[type].run()

    def _unmigrate(self, type):
        if type in self.batches:
            self.batches.pop(type).rollback()


def run_setup(environ=None, output=None, db=None):
    return Setup(environ, output, db).run()
