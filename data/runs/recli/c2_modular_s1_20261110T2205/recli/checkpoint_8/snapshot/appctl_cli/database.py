"""Persistent state store: key-value options and applied-migration history.

The store is a SQLite database under ``<APPCTL_ROOT_DIR>/db/``. All queries
use bound parameters, so keys and values are never interpolated into SQL.
"""

import os
import sqlite3
import time

from .config_loader import root_dir
from .errors import AppctlError

DB_DIR = "db"
DB_FILE = "appctl.sqlite"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"   # UTC, e.g. 2026-11-11T03:10:00Z

SCHEMA = {
    "options": (
        'CREATE TABLE IF NOT EXISTS options ('
        ' "key" TEXT NOT NULL PRIMARY KEY,'
        ' value TEXT NOT NULL,'
        ' modified_on TEXT NOT NULL'
        ')',
        ("key", "value", "modified_on"),
    ),
    "migrations": (
        'CREATE TABLE IF NOT EXISTS migrations ('
        ' migration TEXT NOT NULL,'
        ' type TEXT NOT NULL,'
        ' timestamp TEXT NOT NULL,'
        ' PRIMARY KEY (migration, type)'
        ')',
        ("migration", "type", "timestamp"),
    ),
    "projects": (
        'CREATE TABLE IF NOT EXISTS projects ('
        ' name TEXT NOT NULL PRIMARY KEY,'
        ' path TEXT NOT NULL,'
        ' created_on TEXT NOT NULL'
        ')',
        ("name", "path", "created_on"),
    ),
}


def db_dir(environ=None):
    environ = os.environ if environ is None else environ
    return os.path.join(root_dir(environ), DB_DIR)


def db_path(environ=None):
    return os.path.join(db_dir(environ), DB_FILE)


def utc_now():
    """The current UTC time in the store's timestamp format."""
    return time.strftime(TIMESTAMP_FORMAT, time.gmtime())


def _details(exc):
    if isinstance(exc, OSError) and exc.strerror:
        return f"{exc.strerror}: {exc.filename}" if exc.filename else exc.strerror
    return str(exc)


class Database:
    """A connection to the persistent store, created on first access."""

    def __init__(self, path):
        self.path = path
        self.connection = self._connect()
        self._create_tables()

    def _connect(self):
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            if os.path.isdir(self.path):
                raise sqlite3.OperationalError(f"unable to open database file: {self.path}")
            connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        except (OSError, sqlite3.Error) as exc:
            raise AppctlError(
                f"Unable to initialize connection to appctl sqlite database: {_details(exc)}"
            ) from exc
        return connection

    def _create_tables(self):
        try:
            for table, (statement, columns) in SCHEMA.items():
                self.connection.execute(statement)
                found = {row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")}
                missing = [column for column in columns if column not in found]
                if missing:
                    raise sqlite3.OperationalError(
                        f"table {table} is missing column(s): {', '.join(missing)}"
                    )
        except sqlite3.Error as exc:
            self.close()
            raise AppctlError(f"Encountered Error while creating table: {exc}") from exc

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _execute(self, sql, params=()):
        try:
            return self.connection.execute(sql, params)
        except sqlite3.Error as exc:
            raise AppctlError(f"Unable to query appctl sqlite database: {exc}") from exc

    # -- key-value options ----------------------------------------------------

    def get_option(self, key):
        """Return the stored string for ``key``, or ``False`` when it is missing."""
        row = self._execute('SELECT value FROM options WHERE "key" = ?', (str(key),)).fetchone()
        return False if row is None else str(row[0])

    def set_option(self, key, value):
        """Insert or update ``key``; the value is always stored as a string."""
        self._execute(
            'INSERT INTO options ("key", value, modified_on) VALUES (?, ?, ?) '
            'ON CONFLICT("key") DO UPDATE SET value = excluded.value, '
            'modified_on = excluded.modified_on',
            (str(key), str(value), utc_now()),
        )
        return True

    def delete_option(self, key):
        """Remove ``key``; return whether it existed."""
        return self._execute('DELETE FROM options WHERE "key" = ?', (str(key),)).rowcount > 0

    def get_options(self):
        """All options as ``{key: value}``, ordered by key."""
        rows = self._execute('SELECT "key", value FROM options ORDER BY "key"')
        return {str(key): str(value) for key, value in rows}

    # -- migration history ----------------------------------------------------

    def get_migrations(self, type=None):
        """Applied migrations, ordered by name then type."""
        sql = "SELECT migration, type, timestamp FROM migrations"
        params = ()
        if type is not None:
            sql += " WHERE type = ?"
            params = (str(type),)
        rows = self._execute(sql + " ORDER BY migration, type", params)
        return [{"migration": m, "type": t, "timestamp": ts} for m, t, ts in rows]

    def get_migration_names(self, type=None):
        return [record["migration"] for record in self.get_migrations(type)]

    def is_migration_applied(self, migration, type=None):
        sql = "SELECT 1 FROM migrations WHERE migration = ?"
        params = [str(migration)]
        if type is not None:
            sql += " AND type = ?"
            params.append(str(type))
        return self._execute(sql, params).fetchone() is not None

    def record_migration(self, migration, type):
        """Mark ``migration`` of category ``type`` as applied now."""
        self._execute(
            "INSERT INTO migrations (migration, type, timestamp) VALUES (?, ?, ?) "
            "ON CONFLICT(migration, type) DO UPDATE SET timestamp = excluded.timestamp",
            (str(migration), str(type), utc_now()),
        )
        return True

    def remove_migration(self, migration, type=None):
        """Forget an applied migration; return whether a record was removed."""
        sql = "DELETE FROM migrations WHERE migration = ?"
        params = [str(migration)]
        if type is not None:
            sql += " AND type = ?"
            params.append(str(type))
        return self._execute(sql, params).rowcount > 0

    def apply_migration(self, migration, type, up):
        """Run ``up()`` unless already applied; record it only when it succeeds.

        Returns ``True`` when the migration ran, ``False`` when it was skipped.
        """
        if self.is_migration_applied(migration, type):
            return False
        up()
        self.record_migration(migration, type)
        return True

    def rollback_migration(self, migration, type, down=None):
        """Run ``down()`` (if given) and remove the migration's record."""
        if down is not None:
            down()
        return self.remove_migration(migration, type)

    def run_migrations(self, migrations, type):
        """Apply pending ``(name, up[, down])`` migrations in name order.

        When one fails, its ``down`` is run (if given), nothing is recorded
        for it, and the error is re-raised. Returns the names that ran.
        """
        applied = []
        for entry in sorted(migrations, key=lambda m: str(m[0])):
            name, up = entry[0], entry[1]
            down = entry[2] if len(entry) > 2 else None
            try:
                if self.apply_migration(name, type, up):
                    applied.append(name)
            except Exception:
                self.rollback_migration(name, type, down)
                raise
        return applied

    # -- projects -------------------------------------------------------------

    def add_project(self, name, path):
        """Record project ``name`` whose compose files live in ``path``."""
        self._execute(
            "INSERT INTO projects (name, path, created_on) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET path = excluded.path",
            (str(name), str(path), utc_now()),
        )
        return True

    def get_projects(self):
        """Recorded projects as ``{"name", "path"}`` mappings, ordered by name."""
        rows = self._execute("SELECT name, path FROM projects ORDER BY name")
        return [{"name": name, "path": path} for name, path in rows]

    def remove_project(self, name):
        return self._execute("DELETE FROM projects WHERE name = ?", (str(name),)).rowcount > 0


_instances = {}


def get_db(environ=None):
    """The store for the current root directory, initialized on first access."""
    path = os.path.abspath(db_path(environ))
    db = _instances.get(path)
    if db is None or db.connection is None:
        db = _instances[path] = Database(path)
    return db


def close_all():
    for db in _instances.values():
        db.close()
    _instances.clear()


def get_option(key, environ=None):
    return get_db(environ).get_option(key)


def set_option(key, value, environ=None):
    return get_db(environ).set_option(key, value)


__all__ = ["DB_FILE", "Database", "TIMESTAMP_FORMAT", "close_all", "db_dir", "db_path",
           "get_db", "get_option", "set_option", "utc_now"]
