"""Upgrade orchestration.

Secret: the order of the upgrade phases (disk space check, database
migrations, container migrations, compose tool check, image pulls, global
and per-project container replacement, persisting versions, cleanup), how
the target image versions are found and the current ones observed, where
the global services live, which persistent keys hold the tool and image
versions, and how a failure anywhere restores the pre-upgrade state.
"""

import json
import os
import re
import shutil
import sys

from . import compose_tool as _compose_tool
from . import containers, migrations
from . import messages as _messages
from .errors import CliError
from .output import Output
from .revertable import RevertableStepProcessor

MIN_FREE_BYTES = 5 * 1024 ** 3
VERSION_KEY = "version"
IMAGE_KEY_PREFIX = "image:"
IMAGE_VERSIONS_FILE = "image_versions.json"
BUILTIN_IMAGE_VERSIONS = os.path.join(migrations.TOOL_DIR, IMAGE_VERSIONS_FILE)
GLOBAL_SERVICES_DIR = "services"
_IMAGE_VERSIONS_ENV = "APPCTL_IMAGE_VERSIONS_FILE"
_GROUP = "upgrade"
_IMAGE_LINE = re.compile(
    r"^(?P<lead>\s*(?:-\s*)?image\s*:\s*)(?P<quote>[\"']?)(?P<ref>[^\"'\s#]+)"
    r"(?P=quote)(?P<trail>\s*(?:#.*)?)$")


def _reason(exc):
    return getattr(exc, "message", None) or str(exc) or type(exc).__name__


def _output(out):
    return out or Output(sys.stdout, sys.stderr)


# --- disk space ----------------------------------------------------------------

def _existing(path):
    path = os.path.abspath(path)
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def disk_free(path):
    """Free bytes on the filesystem containing ``path`` (or its nearest
    existing ancestor)."""
    return shutil.disk_usage(_existing(path)).free


def check_disk_space(paths, free=None, minimum=MIN_FREE_BYTES):
    """Raise ``CliError`` unless every filesystem holding ``paths`` has at
    least ``minimum`` free bytes."""
    free = free or disk_free
    for path in paths:
        available = free(path)
        if available < minimum:
            raise CliError(_messages.insufficient_disk_space(path, available / 1024 ** 3))


# --- image versions -----------------------------------------------------------

def _read_versions(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise CliError(_messages.image_versions_unreadable(path, _reason(exc))) from None
    if not isinstance(data, dict):
        raise CliError(_messages.image_versions_unreadable(path, "not a JSON object"))
    return {str(k): str(v) for k, v in data.items()}


def image_version_files(packages_dir=None, env=None, builtin=BUILTIN_IMAGE_VERSIONS):
    """Files declaring target image versions, in the order they apply: the
    tool's, every extension's, then the one named by the environment."""
    files = [builtin] if builtin and os.path.isfile(builtin) else []
    files += [os.path.join(path, IMAGE_VERSIONS_FILE)
              for _, path in migrations.extensions(packages_dir, IMAGE_VERSIONS_FILE)]
    override = (env or {}).get(_IMAGE_VERSIONS_ENV)
    if override:
        files.append(override)
    return files


def target_image_versions(packages_dir=None, env=None, builtin=BUILTIN_IMAGE_VERSIONS):
    """``{repository: tag}`` the tool wants, sorted by repository."""
    versions = {}
    for path in image_version_files(packages_dir, env, builtin):
        versions.update(_read_versions(path))
    return dict(sorted(versions.items()))


def current_image_versions(db, runtime, images):
    """``{repository: tag or None}`` currently in use: the version recorded
    by the last upgrade, else the one observed in the runtime."""
    current = {}
    observed = None
    for image, target in images.items():
        stored = db.get_option(IMAGE_KEY_PREFIX + image)
        if stored is not False:
            current[image] = stored
            continue
        if observed is None:
            observed = {}
            for reference in (runtime.image_references() if runtime else None) or ():
                repository, tag = containers.split_image(reference)
                if tag and tag != "<none>":
                    observed.setdefault(repository, []).append(tag)
        tags = sorted(observed.get(image, ()))
        current[image] = target if target in tags else (tags[-1] if tags else None)
    return current


def changed_images(targets, current):
    """Images whose current tag differs (exact string comparison) from the
    target, in repository order."""
    return [image for image, tag in sorted(targets.items()) if current.get(image) != tag]


def pull_images(runtime, references, out=None):
    """Pull ``references`` one after the other; stop at the first failure."""
    out = _output(out)
    for reference in references:
        out.debug(f"Pulling image {reference}", group=_GROUP)
        out.log_only(f"Pulling image {reference}")
        result = runtime.pull_image(reference)
        if not result.succeeded:
            out.log_only(result.stderr.strip() or f"Pull of {reference} failed.")
            raise CliError(_messages.image_pull_failed(reference))


# --- compose files ------------------------------------------------------------

def rewrite_images(text, targets):
    """``text`` with every ``image:`` line referring to a repository in
    ``targets`` pointing at its target tag."""
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        match = _IMAGE_LINE.match(body)
        if not match:
            continue
        repository, _ = containers.split_image(match.group("ref"))
        if repository not in targets:
            continue
        reference = f"{repository}:{targets[repository]}"
        lines[index] = (match.group("lead") + match.group("quote") + reference
                        + match.group("quote") + match.group("trail") + line[len(body):])
    return "".join(lines)


def service_images(definition):
    """``{service: repository}`` of the services that name an image."""
    services = definition.get("services") if isinstance(definition, dict) else None
    images = {}
    for name, spec in (services or {}).items() if isinstance(services, dict) else ():
        if isinstance(spec, dict) and spec.get("image"):
            images[str(name)] = containers.split_image(spec["image"])[0]
    return images


class ComposeUpgrade:
    """Replaces the containers of (some services of) a compose project with
    ones using the target images, restoring the old containers and compose
    files on failure or on ``rollback``."""

    def __init__(self, runtime, project_dir, targets, services=None, label=None, out=None):
        self.runtime = runtime
        self.project_dir = os.path.abspath(project_dir)
        self.targets = dict(targets)
        self.services = list(services or ())
        self.only_services = services is not None
        self.label = label or self.project_dir
        self.out = _output(out)
        self.files = runtime.compose_files(self.project_dir)
        self._originals = {}
        self._processor = None

    def _check(self, result, action):
        if not result.succeeded:
            detail = result.stderr.strip()
            raise CliError(f"Unable to {action} containers of '{self.label}'"
                           + (f": {detail}" if detail else "."))

    def _remove_containers(self):
        self._check(self.runtime.compose_stop(self.project_dir, self.services), "stop")
        self._check(self.runtime.compose_rm(self.project_dir, self.services), "remove")

    def _start_containers(self):
        self._check(self.runtime.compose_up(self.project_dir, self.services,
                                            no_deps=self.only_services), "start")

    def _rewrite_files(self):
        for path in self.files:
            with open(path, encoding="utf-8", newline="") as handle:
                text = handle.read()
            updated = rewrite_images(text, self.targets)
            if updated != text:
                self._originals[path] = text
                with open(path, "w", encoding="utf-8", newline="") as handle:
                    handle.write(updated)

    def _restore_files(self):
        originals, self._originals = self._originals, {}
        for path, text in originals.items():
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)

    def execute(self):
        processor = RevertableStepProcessor(self.out)
        processor.add_step(f"remove old containers of {self.label}",
                           self._remove_containers, self._start_containers)
        processor.add_step(f"update compose files of {self.label}",
                           self._rewrite_files, self._restore_files)
        processor.add_step(f"start new containers of {self.label}",
                           self._start_containers, self._remove_containers)
        if not processor.execute():
            raise processor.error if isinstance(processor.error, CliError) else CliError(
                _reason(processor.error))
        self._processor = processor
        return True

    def rollback(self):
        if self._processor is not None:
            self._processor.rollback()
            self._processor = None


def global_upgrade(runtime, root_dir, changed, targets, out=None):
    """The ``ComposeUpgrade`` of the global services whose image changed, or
    ``None`` when there is nothing to replace."""
    directory = os.path.join(root_dir, GLOBAL_SERVICES_DIR)
    if not containers.base_compose_file(directory):
        return None
    definition = containers.load_compose(runtime.compose_files(directory))
    services = [name for name, image in service_images(definition).items()
                if image in changed]
    if not services:
        return None
    return ComposeUpgrade(runtime, directory, {i: targets[i] for i in changed},
                          services=services, label="global services", out=out)


def project_upgrade(runtime, project, changed, targets, out=None):
    """The ``ComposeUpgrade`` of a registered project using a changed image,
    or ``None`` when the project is skipped."""
    out = _output(out)
    name, directory = project["name"], project["path"]
    if not os.path.isdir(directory) or not containers.base_compose_file(directory):
        out.warning(_messages.project_skipped(name, f"no compose file in '{directory}'."))
        return None
    definition = containers.load_compose(runtime.compose_files(directory))
    if not set(service_images(definition).values()) & set(changed):
        out.debug(f"No image of project '{name}' changed.", group=_GROUP)
        return None
    return ComposeUpgrade(runtime, directory, {i: targets[i] for i in changed},
                          label=f"project {name}", out=out)


# --- orchestration ------------------------------------------------------------

class Upgrader:
    """Brings the installation up to ``version``.

    Every phase is a revertable step; when one fails the earlier ones are
    undone (migrations rolled back, containers and compose files restored,
    the compose tool restored, persisted versions reset), the failure is
    reported and ``CliError`` with the generic migration error is raised.
    Pruning old images and networks happens only after success, and its
    failures are reported as warnings.
    """

    def __init__(self, db, out, env, root_dir, version, packages_dir=None, runtime=None,
                 sources=None, targets=None, compose=None, free=None):
        self.db = db
        self.out = _output(out)
        self.env = dict(env or {})
        self.root_dir = root_dir
        self.version = version
        self.packages_dir = packages_dir
        self.runtime = runtime or containers.Runtime(out=self.out, env=self.env,
                                                     cwd=root_dir, config={})
        self.sources = sources
        self._targets = targets
        self.compose = compose
        self.free = free
        self.changed = []
        self.current = {}
        self._persisted = {}
        self._container_upgrades = []
        self._runtime_installed = False

    # --- phases -------------------------------------------------------------

    def check_disk_space(self):
        paths = [self.root_dir]
        if self._runtime_installed:
            paths.append(self.runtime.root_dir())
        else:
            paths.append(containers.DEFAULT_ROOT_DIR)
        check_disk_space(paths, free=self.free)

    def _context(self, migration):
        return migrations.MigrationContext(migration, self.db, self.out, env=self.env,
                                           root_dir=self.root_dir, runtime=self.runtime)

    def _batch(self, migration_type):
        sources = self.sources if self.sources is not None else migrations.default_sources(
            self.packages_dir, self.out)
        pending = migrations.pending(self.db, sources, migration_type)
        return migrations.MigrationBatch(self.db, self.out, pending, self._context)

    def _migration_step(self, processor, migration_type):
        holder = {}

        def up():
            holder["batch"] = self._batch(migration_type)
            return holder["batch"].execute()

        def down():
            if "batch" in holder:
                holder["batch"].rollback()

        processor.add_step(f"{migration_type} migrations", up, down)

    def _compose_tool(self):
        if self.compose is None:
            self.compose = _compose_tool.ComposeTool(self.runtime, self.out, self.env)
        try:
            self.compose.ensure()
        except CliError as exc:
            self.out.warning(_messages.compose_upgrade_failed(_reason(exc).rstrip(".")))

    def _restore_compose_tool(self):
        if self.compose is not None:
            self.compose.restore()

    def targets(self):
        if self._targets is None:
            self._targets = target_image_versions(self.packages_dir, self.env)
        return self._targets

    def _pull(self):
        targets = self.targets()
        self.current = current_image_versions(self.db, self.runtime, targets)
        self.changed = changed_images(targets, self.current)
        pull_images(self.runtime, [f"{i}:{targets[i]}" for i in self.changed], self.out)

    def _upgrade_containers(self):
        upgrades = []
        upgrade = global_upgrade(self.runtime, self.root_dir, self.changed, self.targets(),
                                 self.out)
        if upgrade is not None:
            upgrades.append(upgrade)
        for project in self.db.get_projects():
            upgrade = project_upgrade(self.runtime, project, self.changed, self.targets(),
                                      self.out)
            if upgrade is not None:
                upgrades.append(upgrade)
        for upgrade in upgrades:
            self._container_upgrades.append(upgrade)
            upgrade.execute()

    def _revert_containers(self):
        upgrades, self._container_upgrades = self._container_upgrades, []
        for upgrade in reversed(upgrades):
            try:
                upgrade.rollback()
            except Exception as exc:  # noqa: BLE001 - keep restoring the others
                self.out.warning(f"Unable to restore containers of {upgrade.label}: "
                                 f"{_reason(exc)}")

    def _persist(self):
        values = {VERSION_KEY: self.version}
        if self._runtime_installed:
            for image, tag in self.targets().items():
                values[IMAGE_KEY_PREFIX + image] = tag
        for key, value in values.items():
            self._persisted[key] = self.db.get_option(key)
            self.db.update_option(key, value)

    def _restore_persisted(self):
        persisted, self._persisted = self._persisted, {}
        for key, previous in persisted.items():
            if previous is False:
                self.db.delete_option(key)
            else:
                self.db.update_option(key, previous)

    def _cleanup(self):
        if self.compose is not None:
            try:
                self.compose.cleanup()
            except OSError as exc:
                self.out.warning(_messages.cleanup_failed("compose tool backup", _reason(exc)))
        if not self._runtime_installed:
            return
        old = [f"{image}:{self.current[image]}" for image in self.changed
               if self.current.get(image) and self.current[image] != self.targets()[image]]
        jobs = [("images", lambda ref=ref: self.runtime.remove_image(ref)) for ref in old]
        jobs += [("images", self.runtime.prune_images),
                 ("networks", self.runtime.prune_networks)]
        for what, job in jobs:
            try:
                result = job()
                if not result.succeeded:
                    self.out.log_only(_messages.cleanup_failed(
                        what, result.stderr.strip() or f"exit code {result.return_code}"))
            except Exception as exc:  # noqa: BLE001 - cleanup never fails the upgrade
                self.out.warning(_messages.cleanup_failed(what, _reason(exc)))

    # --- entry point --------------------------------------------------------

    def run(self):
        self._runtime_installed = self.runtime.is_installed()
        self.check_disk_space()
        processor = RevertableStepProcessor(self.out)
        self._migration_step(processor, migrations.DB)
        self._migration_step(processor, migrations.CONTAINER)
        if self._runtime_installed:
            processor.add_step("compose tool", self._compose_tool, self._restore_compose_tool)
            processor.add_step("pull images", self._pull)
            processor.add_step("upgrade containers", self._upgrade_containers,
                               self._revert_containers)
        processor.add_step("persist versions", self._persist, self._restore_persisted)
        if not processor.execute():
            error = processor.error
            if isinstance(error, CliError):
                self.out.report(error)
            else:
                self.out.error(_reason(error))
            raise CliError(_messages.migration_error())
        self._cleanup()
        return True


def stored_version(db):
    value = db.get_option(VERSION_KEY)
    return None if value is False else value

