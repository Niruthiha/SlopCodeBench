import io
import json
import os
import re
import subprocess
import sys

import pytest

from appctl_core import catalog
from appctl_core.app import run
from appctl_core.command_tree import CommandTree
from appctl_core.errors import CliError
from appctl_core.output import color_enabled

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAMP = re.compile(r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\] ")


class Tty(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def root(tmp_path):
    return tmp_path / "root"


def call(root, *argv, stdin="", stdout=None, tree=None):
    out, err = stdout or io.StringIO(), io.StringIO()
    code = run(list(argv), {"APPCTL_ROOT_DIR": str(root)}, out, err,
               tree=tree, cwd=str(root.parent), stdin=io.StringIO(stdin))
    return code, out.getvalue(), err.getvalue()


def log_text(root):
    return (root / "logs" / "appctl.log").read_text()


# --- formats ------------------------------------------------------------------

def test_formats(root):
    code, out, _ = call(root, "post", "list", "--format=json")
    assert code == 0 and out.startswith("[\n    {\n        \"ID\": 1,")
    assert list(json.loads(out)[0]) == ["ID", "post_title", "post_status", "post_type"]
    assert call(root, "post", "list", "--format=count")[1] == "2\n"
    assert call(root, "post", "list", "--format=ids")[1] == "1 2\n"
    assert call(root, "post", "list", "--format=csv", "--fields=title,ID")[1] == (
        "post_title,ID\nHello world!,1\nSample Page,2\n")
    assert call(root, "post", "list", "--format=yaml")[1].startswith("---\n- ID: 1\n")


def test_table_columns_follow_fields_and_align(root):
    out = call(root, "post", "list", "--fields=post_type,ID")[1]
    lines = out.splitlines()
    assert lines[0].split() == ["post_type", "ID"]
    assert {l.index(l.split()[1]) for l in lines} == {len("post_type") + 2}


def test_single_item_is_vertical(root):
    out = call(root, "user", "get", "admin", "--fields=EMAIL,login")[1]
    assert out.splitlines() == ["Field       Value",
                                "user_email  admin@example.com",
                                "user_login  admin"]


def test_field_and_invalid_field(root):
    assert call(root, "user", "list", "--field=login") == (0, "admin\neditor\n", "")
    assert call(root, "post", "list", "--fields=ID,bogus") == (
        1, "", "Error: Invalid field: bogus.\n")
    assert call(root, "post", "list", "--field=nope")[2] == "Error: Invalid field: nope.\n"


# --- message categories ----------------------------------------------------------

def test_colors(root):
    assert color_enabled("auto", Tty()) and not color_enabled("auto", io.StringIO())
    assert not color_enabled("auto", Tty(), os_name="nt")
    assert "\x1b[" in call(root, "nosuch", stdout=Tty())[2]
    assert call(root, "nosuch", "--no-color", stdout=Tty())[2].startswith("Error:")
    assert call(root, "nosuch", "--color")[2].startswith("\x1b[1;31mError:\x1b[0m")


def test_quiet_and_logging(root):
    assert call(root, "plugin", "activate", "akismet", "--quiet") == (0, "", "")
    code, out, _ = call(root, "plugin", "activate", "akismet")
    assert "Plugin 'akismet' activated." in out and "Success:" in out
    log = log_text(root)
    assert "Plugin 'akismet' activated." in log and "Success" not in log
    assert all(STAMP.match(line) for line in log.splitlines())
    assert log.count("appctl invocation") == 2


def test_debug_groups(root):
    err = call(root, "--debug", "site", "list")[2]
    assert re.search(r"^Debug \(bootstrap\): .* \(\d+\.\d{3}s\)$", err, re.M)
    assert "Debug (bootstrap)" in call(root, "--debug=bootstrap", "site", "list")[2]
    assert call(root, "--debug=other", "site", "list")[2] == ""
    assert "Debug (bootstrap)" in log_text(root)


def test_multi_line_error_box(root):
    tree = CommandTree()
    catalog.register_all(tree)
    tree.register("boom", lambda ctx: (_ for _ in ()).throw(CliError(["a", "bb"], 3)))
    code, _, err = call(root, "boom", tree=tree)
    assert code == 3
    assert err == "+----------+\n| Error: a |\n| bb       |\n+----------+\n"


def test_completion_not_logged(root):
    assert call(root, "cli", "completions", "--line=appctl si", "--point=9")[1] == "site\n"
    assert call(root, "cli", "completion", "--line=appctl si", "--point=9")[1] == "site\n"
    assert not (root / "logs" / "appctl.log").exists()


def test_sensitive_info_not_logged(root):
    code, out, _ = call(root, "user", "reset-password", "admin",
                        "--password=hunter2", "--show-password")
    assert "Password: hunter2" in out and "hunter2" not in log_text(root)
    assert call(root, "user", "reset-password", "admin", "--password=x",
                "--show-password", "--quiet")[1] == ""


# --- input ---------------------------------------------------------------------

def test_confirmation(root):
    code, out, err = call(root, "site", "delete", "foo", stdin=" Y \n")
    assert code == 0 and "[y/n]" in out and "Success" in out
    code, out, err = call(root, "site", "delete", "foo", stdin="yes\n")
    assert "Success" not in out and err == "Warning: Operation cancelled.\n"
    assert "Success" in call(root, "site", "delete", "foo", "--yes")[1]


def test_stdin_fallback(root):
    assert call(root, "config", "get", stdin="DB_NAME\n")[1] == "app\n"
    assert call(root, "option", "add", "k", "--format=json", stdin='{"a": 1}')[0] == 0
    assert call(root, "option", "add", "k", "--format=json", stdin="{oops") == (
        1, "", "Error: Invalid JSON: {oops\n")
    assert "{oops" not in log_text(root)


def test_subprocess_stdin_json_error(tmp_path):
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "appctl.py"), "option", "update", "k",
         "--format=json"], input="not json", capture_output=True, text=True,
        env=dict(os.environ, APPCTL_ROOT_DIR=str(tmp_path)))
    assert proc.returncode == 1 and proc.stderr == "Error: Invalid JSON: not json\n"
