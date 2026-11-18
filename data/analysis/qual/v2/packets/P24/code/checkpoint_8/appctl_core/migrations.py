"""Versioned migrations.

Secret: where migration artifacts are looked for (the tool's own data
directory and every installed extension), the file naming convention and
the resulting order, how a migration is identified in the history (so that
same-named migrations of different sources stay distinct), how artifacts
are loaded and called, and how a failed batch is rolled back.

Convention: ``<source>/migrations/<type>/<digits>_<name>.py`` where
``<type>`` is ``db`` or ``container``. The artifact defines ``up`` and
optionally ``down`` (module functions, or methods of a ``Migration``
class); each accepts either no argument or a ``MigrationContext``.
Pending migrations run in ascending order of their numeric prefix, then
file name, then source (the tool before extensions, extensions by name).
The history records ``<source>:<file name without .py>``.
"""

import hashlib
import importlib.util
import inspect
import os
import re
import sys

from . import messages as _messages
from .errors import CliError

DB = "db"
CONTAINER = "container"
TYPES = (DB, CONTAINER)
TOOL_SOURCE = "appctl"
TOOL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_MIGRATIONS_DIR = "migrations"
_FILE_PATTERN = re.compile(r"^(\d+)_([A-Za-z0-9][A-Za-z0-9_.-]*)\.py$")
_SEPARATOR = ":"
_EXTENSION_DEPTH = 2


class Source:
    """Somewhere migrations come from: the tool or one extension."""

    def __init__(self, name, base_dir, is_tool=False):
        self.name = name
        self.base_dir = base_dir
        self.is_tool = is_tool

    def directory(self, migration_type):
        return os.path.join(self.base_dir, _MIGRATIONS_DIR, migration_type)

    def __repr__(self):
        return f"Source({self.name!r}, {self.base_dir!r})"


class Migration:
    """One discovered migration artifact."""

    def __init__(self, source, migration_type, path):
        self.source = source
        self.type = migration_type
        self.path = path
        self.file_name = os.path.basename(path)
        self.name = self.file_name[:-3]
        match = _FILE_PATTERN.match(self.file_name)
        self.order = int(match.group(1)) if match else 0
        self._module = None

    @property
    def identity(self):
        """The name recorded in the migration history."""
        return identity(self.source.name, self.name)

    def sort_key(self):
        return (self.order, self.name, not self.source.is_tool, self.source.name)

    def __repr__(self):
        return f"Migration({self.identity!r}, {self.type!r})"

    # --- loading and calling ------------------------------------------------

    def load(self):
        """Load the artifact from the file it was discovered at."""
        if self._module is not None:
            return self._module
        if not os.path.isfile(self.path):
            raise MigrationFileNotFound(_messages.migration_file_not_found(self.path))
        digest = hashlib.sha1(self.path.encode("utf-8", "surrogateescape")).hexdigest()[:12]
        module_name = f"appctl_migration_{self.type}_{digest}"
        spec = importlib.util.spec_from_file_location(module_name, self.path)
        if spec is None or spec.loader is None:
            raise MigrationFileNotFound(_messages.migration_file_not_found(self.path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except FileNotFoundError:
            if os.path.isfile(self.path):
                raise
            raise MigrationFileNotFound(_messages.migration_file_not_found(self.path)) from None
        finally:
            sys.modules.pop(module_name, None)
        self._module = module
        return module

    def _target(self):
        module = self.load()
        cls = getattr(module, "Migration", None)
        if inspect.isclass(cls):
            return cls()
        return module

    def _call(self, name, context, required):
        target = self._target()
        function = getattr(target, name, None)
        if not callable(function):
            if required:
                raise CliError(_messages.migration_without_up(self.path))
            return None
        return function(context) if _accepts_argument(function) else function()

    def up(self, context):
        return self._call("up", context, required=True)

    def down(self, context):
        return self._call("down", context, required=False)


class MigrationFileNotFound(CliError):
    """A migration artifact is missing from where it was discovered."""


def _accepts_argument(function):
    try:
        params = inspect.signature(function).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(p.kind == p.VAR_POSITIONAL or
               (p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty)
               for p in params)


def identity(source_name, name):
    return f"{source_name}{_SEPARATOR}{name}"


# --- discovery ---------------------------------------------------------------

def tool_source(base_dir=None):
    return Source(TOOL_SOURCE, base_dir or TOOL_DIR, is_tool=True)


def extensions(packages_dir, marker):
    """``(name, directory)`` of every installed extension shipping ``marker``
    (a file or directory name), sorted by name. Extensions live at most two
    levels below ``packages_dir`` (e.g. ``name`` or ``vendor/name``)."""
    found = []

    def walk(directory, parts):
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            return
        for name in names:
            path = os.path.join(directory, name)
            if name.startswith(".") or not os.path.isdir(path):
                continue
            if os.path.exists(os.path.join(path, marker)):
                found.append(("/".join(parts + [name]), path))
            elif len(parts) + 1 < _EXTENSION_DEPTH:
                walk(path, parts + [name])

    if packages_dir and os.path.isdir(packages_dir):
        walk(packages_dir, [])
    return sorted(found)


def extension_sources(packages_dir, out=None):
    """Every installed extension that ships migrations, sorted by name."""
    sources = []
    for name, path in extensions(packages_dir, _MIGRATIONS_DIR):
        if name == TOOL_SOURCE:
            if out is not None:
                out.warning(_messages.migration_source_reserved(path))
            continue
        sources.append(Source(name, path))
    return sources


def default_sources(packages_dir=None, out=None, tool_dir=None):
    return [tool_source(tool_dir)] + extension_sources(packages_dir, out)


def discover(sources, migration_type):
    """Every migration of ``migration_type`` found in ``sources``, in order."""
    found = []
    for source in sources:
        directory = source.directory(migration_type)
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            path = os.path.join(directory, name)
            if _FILE_PATTERN.match(name) and os.path.isfile(path):
                found.append(Migration(source, migration_type, path))
    return sorted(found, key=Migration.sort_key)


def pending(db, sources, migration_type):
    """Discovered migrations not yet in the history, in ascending order."""
    applied = {m["migration"] for m in db.get_migrations(migration_type)}
    return [m for m in discover(sources, migration_type) if m.identity not in applied]


# --- execution -----------------------------------------------------------------

class MigrationContext:
    """What a migration may use."""

    def __init__(self, migration, db, out, env=None, root_dir=None, runtime=None):
        self.migration = migration
        self.db = db
        self.out = out
        self.env = dict(env or {})
        self.root_dir = root_dir
        self.runtime = runtime

    @property
    def name(self):
        return self.migration.name

    @property
    def identity(self):
        return self.migration.identity

    @property
    def source(self):
        return self.migration.source.name

    @property
    def type(self):
        return self.migration.type


def _reason(exc):
    return getattr(exc, "message", None) or str(exc) or type(exc).__name__


class MigrationBatch:
    """Runs pending migrations of one type as a unit.

    Each migration that succeeds is recorded in the history at once. When
    one fails, the migrations completed in this batch are rolled back in
    reverse order (``down`` is called and the record removed) and a
    ``CliError`` is raised. ``rollback`` undoes a successful batch.
    """

    def __init__(self, db, out, migrations, context_factory=None):
        self.db = db
        self.out = out
        self.migrations = list(migrations)
        self.completed = []
        self._context_factory = context_factory or (
            lambda migration: MigrationContext(migration, db, out))

    def execute(self):
        if not self.migrations:
            return True
        for migration in self.migrations:
            self.out.debug(f"Running migration: {migration.identity}", group="migration")
            self.out.log_only(f"Running {migration.type} migration: {migration.identity}")
            try:
                migration.up(self._context_factory(migration))
                self.db.add_migration(migration.identity, migration.type)
            except Exception as exc:  # noqa: BLE001 - any failure aborts the batch
                self.out.log_only(f"Migration {migration.identity} failed: {_reason(exc)}")
                self.rollback()
                if isinstance(exc, MigrationFileNotFound):
                    raise
                raise CliError(_messages.migration_failed(
                    migration.identity, _reason(exc))) from exc
            self.completed.append(migration)
            self.out.log_only(f"Migration {migration.identity} completed.")
        return True

    def rollback(self):
        completed, self.completed = self.completed, []
        for migration in reversed(completed):
            self.out.debug(f"Rolling back migration: {migration.identity}", group="migration")
            self.out.log_only(f"Rolling back {migration.type} migration: {migration.identity}")
            try:
                migration.down(self._context_factory(migration))
            except Exception as exc:  # noqa: BLE001 - rollback must go on
                self.out.warning(_messages.migration_rollback_failed(
                    migration.identity, _reason(exc)))
            try:
                self.db.remove_migration(migration.identity, migration.type)
            except Exception as exc:  # noqa: BLE001
                self.out.warning(_messages.migration_rollback_failed(
                    migration.identity, _reason(exc)))
