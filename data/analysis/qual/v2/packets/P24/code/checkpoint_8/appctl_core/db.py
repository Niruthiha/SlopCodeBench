"""Persistent state database.

Secret: where the SQLite file lives, the table layout used for key/value
options, for the migration history and for the registered projects, the timestamp format, and how
connection and schema failures are reported.
"""

import os
import sqlite3
from datetime import datetime, timezone

from . import messages
from .errors import CliError

_SUBDIR = "db"
_FILE_NAME = "appctl.sqlite"
_TIMESTAMP = "%Y-%m-%dT%H:%M:%SZ"
_BUSY_TIMEOUT = 30

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS options (
        key TEXT NOT NULL PRIMARY KEY,
        value TEXT NOT NULL,
        modified_on TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS migrations (
        migration TEXT NOT NULL,
        type TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        PRIMARY KEY (migration, type)
    )""",
    """CREATE TABLE IF NOT EXISTS projects (
        name TEXT NOT NULL PRIMARY KEY,
        path TEXT NOT NULL,
        created_on TEXT NOT NULL
    )""",
)


def db_dir(root_dir):
    return os.path.join(root_dir, _SUBDIR)


def db_path(root_dir):
    """``<root_dir>/db/appctl.sqlite``."""
    return os.path.join(db_dir(root_dir), _FILE_NAME)


def timestamp(now=None):
    """UTC timestamp in ISO 8601 form, e.g. ``2026-01-02T03:04:05Z``."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).strftime(_TIMESTAMP)


def _details(exc):
    if isinstance(exc, OSError):
        return getattr(exc, "strerror", None) or str(exc)
    return str(exc)


def _text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="surrogateescape")
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


class Database:
    """Key/value options and migration history kept in a SQLite file.

    The file and its tables are created on first access. Failures raise a
    ``CliError`` carrying the user-facing message.
    """

    def __init__(self, path):
        self.path = str(path)
        self._conn = None
        self._connect()
        self._create_tables()

    # --- setup ------------------------------------------------------------

    def _connect(self):
        try:
            directory = os.path.dirname(self.path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory, exist_ok=True)
            self._conn = sqlite3.connect(self.path, timeout=_BUSY_TIMEOUT,
                                         isolation_level=None)
        except (OSError, sqlite3.Error) as exc:
            raise CliError(messages.db_connection_failed(_details(exc))) from exc

    def _create_tables(self):
        try:
            with self._transaction():
                for statement in _SCHEMA:
                    self._conn.execute(statement)
        except sqlite3.Error as exc:
            self.close()
            raise CliError(messages.db_table_creation_failed(_details(exc))) from exc

    def _transaction(self):
        return _Transaction(self._conn)

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    # --- options ----------------------------------------------------------

    def get_option(self, key):
        """The stored string for ``key``, or ``False`` when it is not set."""
        row = self._conn.execute("SELECT value FROM options WHERE key = ?",
                                 (_text(key),)).fetchone()
        return False if row is None else _text(row[0])

    def update_option(self, key, value):
        """Insert or replace the value stored under ``key``."""
        with self._transaction():
            self._conn.execute(
                "INSERT INTO options (key, value, modified_on) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "modified_on = excluded.modified_on",
                (_text(key), _text(value), timestamp()))
        return True

    def delete_option(self, key):
        """Forget ``key``; ``True`` when a value was removed."""
        with self._transaction():
            cursor = self._conn.execute("DELETE FROM options WHERE key = ?", (_text(key),))
        return cursor.rowcount > 0

    def get_options(self):
        """Every option as ``{key, value, modified_on}``, ordered by key."""
        rows = self._conn.execute(
            "SELECT key, value, modified_on FROM options ORDER BY key")
        return [{"key": _text(k), "value": _text(v), "modified_on": _text(m)}
                for k, v, m in rows]

    # --- migrations -------------------------------------------------------

    def get_migrations(self, migration_type=None):
        """Applied migrations as ``{migration, type, timestamp}``, ordered by
        type and then name; optionally only those of ``migration_type``."""
        query = "SELECT migration, type, timestamp FROM migrations"
        params = ()
        if migration_type is not None:
            query += " WHERE type = ?"
            params = (_text(migration_type),)
        query += " ORDER BY type, migration"
        return [{"migration": _text(m), "type": _text(t), "timestamp": _text(s)}
                for m, t, s in self._conn.execute(query, params)]

    def is_migrated(self, migration, migration_type):
        row = self._conn.execute(
            "SELECT 1 FROM migrations WHERE migration = ? AND type = ?",
            (_text(migration), _text(migration_type))).fetchone()
        return row is not None

    def add_migration(self, migration, migration_type):
        """Record ``migration`` as applied now."""
        with self._transaction():
            self._conn.execute(
                "INSERT INTO migrations (migration, type, timestamp) VALUES (?, ?, ?) "
                "ON CONFLICT(migration, type) DO UPDATE SET timestamp = excluded.timestamp",
                (_text(migration), _text(migration_type), timestamp()))
        return True

    def remove_migration(self, migration, migration_type):
        """Forget ``migration``; ``True`` when a record was removed."""
        with self._transaction():
            cursor = self._conn.execute(
                "DELETE FROM migrations WHERE migration = ? AND type = ?",
                (_text(migration), _text(migration_type)))
        return cursor.rowcount > 0

    def run_migration(self, migration, migration_type, up):
        """Run ``up()`` unless ``migration`` was already applied; record it
        once ``up`` completes. Return whether it ran."""
        if self.is_migrated(migration, migration_type):
            return False
        up()
        self.add_migration(migration, migration_type)
        return True

    def rollback_migration(self, migration, migration_type, down=None):
        """Run ``down()`` (if given) for an applied migration and remove its
        record. Return whether it was rolled back."""
        if not self.is_migrated(migration, migration_type):
            return False
        if down is not None:
            down()
        self.remove_migration(migration, migration_type)
        return True

    # --- projects ---------------------------------------------------------

    def add_project(self, name, path):
        """Register (or move) project ``name`` living in directory ``path``."""
        with self._transaction():
            self._conn.execute(
                "INSERT INTO projects (name, path, created_on) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET path = excluded.path",
                (_text(name), _text(path), timestamp()))
        return True

    def remove_project(self, name):
        with self._transaction():
            cursor = self._conn.execute("DELETE FROM projects WHERE name = ?",
                                        (_text(name),))
        return cursor.rowcount > 0

    def get_projects(self):
        """Every project as ``{name, path, created_on}``, ordered by name."""
        rows = self._conn.execute(
            "SELECT name, path, created_on FROM projects ORDER BY name")
        return [{"name": _text(n), "path": _text(p), "created_on": _text(c)}
                for n, p, c in rows]


class _Transaction:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        self._conn.execute("BEGIN IMMEDIATE")

    def __exit__(self, exc_type, exc, tb):
        self._conn.execute("COMMIT" if exc_type is None else "ROLLBACK")
        return False


def open_database(root_dir):
    """The database below ``root_dir`` (created on first access)."""
    return Database(db_path(root_dir))
