import io
import os
import re
import sqlite3

import pytest

from appctl_core import db
from appctl_core.app import run
from appctl_core.errors import CliError

IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def call(tmp_path, *argv):
    out, err = io.StringIO(), io.StringIO()
    env = {"APPCTL_ROOT_DIR": str(tmp_path / "root"), "PATH": os.environ.get("PATH", "")}
    code = run(list(argv), env, out, err, cwd=str(tmp_path), stdin=io.StringIO(""))
    return code, out.getvalue(), err.getvalue()


def test_store_is_created_on_first_invocation(tmp_path):
    assert call(tmp_path, "cli", "version")[:2] == (0, "1.0.0\n")
    path = tmp_path / "root" / "db" / "appctl.sqlite"
    assert path.is_file()
    tables = {r[0] for r in sqlite3.connect(path).execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"options", "migrations"} <= tables


def test_options_persist_and_upsert(tmp_path):
    with db.open_database(str(tmp_path)) as store:
        assert store.get_option("missing") is False
        store.update_option("k", 42)
        assert store.get_option("k") == "42"
        store.update_option("k", "0123")
        assert store.get_option("k") == "0123"
    with db.open_database(str(tmp_path)) as store:
        assert store.get_option("k") == "0123"
        [row] = store.get_options()
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", row["modified_on"])


def test_untrusted_values_are_stored_verbatim(tmp_path):
    with db.open_database(str(tmp_path)) as store:
        nasty = "x'); DROP TABLE options; --"
        store.update_option(nasty, nasty)
        assert store.get_option(nasty) == nasty
        assert store.get_option("' OR '1'='1") is False


def test_migration_history(tmp_path):
    ran = []
    with db.open_database(str(tmp_path)) as store:
        assert store.run_migration("b", "db", lambda: ran.append("b"))
        assert store.run_migration("a", "db", lambda: ran.append("a"))
        assert store.run_migration("z", "container", lambda: ran.append("z"))
        assert not store.run_migration("a", "db", lambda: ran.append("again"))
    with db.open_database(str(tmp_path)) as store:
        names = [(m["type"], m["migration"]) for m in store.get_migrations()]
        assert names == [("container", "z"), ("db", "a"), ("db", "b")]
        assert [m["migration"] for m in store.get_migrations("db")] == ["a", "b"]

        def fail():
            raise RuntimeError("boom")
        with pytest.raises(RuntimeError):
            store.run_migration("c", "db", fail)
        assert not store.is_migrated("c", "db")
        assert store.rollback_migration("a", "db", lambda: ran.append("down"))
        assert not store.is_migrated("a", "db")
        assert not store.rollback_migration("a", "db")
    assert ran == ["b", "a", "z", "down"]


def test_connection_failure(tmp_path):
    (tmp_path / "root").mkdir()
    (tmp_path / "root" / "db").write_text("not a directory")
    code, out, err = call(tmp_path, "cli", "version")
    assert (code, out) == (1, "")
    assert err.startswith("Error: Unable to initialize connection to appctl sqlite database: ")
    assert err.count("\n") == 1


def test_connection_failure_when_file_is_a_directory(tmp_path):
    (tmp_path / "root" / "db" / "appctl.sqlite").mkdir(parents=True)
    with pytest.raises(CliError, match="^Unable to initialize connection to appctl sqlite"):
        db.open_database(str(tmp_path / "root"))


def test_table_creation_failure(tmp_path):
    path = tmp_path / "root" / "db" / "appctl.sqlite"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is definitely not a sqlite database file" * 10)
    code, out, err = call(tmp_path, "cli", "version")
    assert (code, out) == (1, "")
    assert err.startswith("Error: Encountered Error while creating table: ")
