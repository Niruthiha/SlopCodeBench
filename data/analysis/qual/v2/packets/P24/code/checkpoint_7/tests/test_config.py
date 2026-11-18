import io
import json
import os
import stat
import subprocess
import sys

import pytest

from appctl_core import yaml_lite
from appctl_core.app import run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def home(tmp_path):
    root = tmp_path / "root"
    project = tmp_path / "project"
    project.mkdir()
    return root, project


def call(*argv, root, cwd, env=None):
    out, err = io.StringIO(), io.StringIO()
    full_env = {"APPCTL_ROOT_DIR": str(root), "PATH": os.environ.get("PATH", "")}
    full_env.update(env or {})
    code = run(list(argv), full_env, out, err, cwd=str(cwd))
    return code, out.getvalue(), err.getvalue()


def info(root, cwd, *extra, env=None):
    code, out, err = call("cli", "info", "--format=json", *extra,
                          root=root, cwd=cwd, env=env)
    assert code == 0, err
    return json.loads(out)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# --- loading and precedence ------------------------------------------------

def test_global_config_auto_created(home):
    root, project = home
    call("cli", "version", root=root, cwd=project)
    data = yaml_lite.load((root / "config" / "config.yml").read_text())
    assert data == {"locale": "en_US", "installer_version": "stable"}


def test_auto_create_preserves_existing_values(home, tmp_path):
    root, project = home
    config = tmp_path / "custom.yml"
    write(config, "color: false\nlocale: fr_FR")
    call("cli", "version", root=root, cwd=project,
         env={"APPCTL_CONFIG_PATH": str(config)})
    assert yaml_lite.load(config.read_text()) == {
        "color": False, "locale": "fr_FR", "installer_version": "stable"}


def test_unwritable_global_config(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("running with privileges that ignore permissions")
        code, _, err = call("cli", "version", root=tmp_path, cwd=tmp_path,
                            env={"APPCTL_CONFIG_PATH": str(locked / "c.yml")})
    finally:
        locked.chmod(stat.S_IRWXU)
    assert code == 1 and err.startswith("Error: ")


def test_precedence_runtime_project_global_default(home):
    root, project = home
    assert info(root, project)["color"] == "auto"
    write(root / "config" / "config.yml", "color: true\n")
    assert info(root, project)["color"] is True
    write(project / "appctl.yml", "color: false\n")
    assert info(root, project)["color"] is False
    assert info(root, project, "--color")["color"] is True


def test_project_config_search_and_local_priority(home):
    root, project = home
    nested = project / "a" / "b"
    nested.mkdir(parents=True)
    write(project / "appctl.yml", "color: true\n")
    assert info(root, nested)["project_config_path"] == str(project / "appctl.yml")
    write(project / "appctl.local.yml", "color: false\n")
    data = info(root, nested)
    assert data["project_config_path"] == str(project / "appctl.local.yml")
    assert data["color"] is False
    write(project / "a" / "appctl.yml", "{}\n")
    assert info(root, nested)["project_config_path"] == str(project / "a" / "appctl.yml")


def test_file_cannot_set_runtime_only_params(home):
    root, project = home
    write(project / "appctl.yml", "quiet: true\ndebug: true\n")
    data = info(root, project)
    assert data["quiet"] is False and data["debug"] is False


def test_packages_dir(home):
    root, project = home
    assert info(root, project)["packages_dir"] == str(root / "packages")
    data = info(root, project, env={"APPCTL_PACKAGES_DIR": "/opt/pkgs"})
    assert data["packages_dir"] == "/opt/pkgs"


def test_inherit_and_merge(home):
    root, project = home
    write(project / "base.yml", "disabled_commands: [site list]\ncolor: true\n")
    write(project / "appctl.yml",
          "_:\n  inherit: base.yml\n  merge: true\ndisabled_commands: [plugin list]\n")
    assert call("site", "list", root=root, cwd=project)[0] == 1
    assert call("plugin", "list", root=root, cwd=project)[0] == 1
    assert info(root, project)["color"] is True
    write(project / "appctl.yml",
          "_:\n  inherit: base.yml\ndisabled_commands: [plugin list]\ncolor: false\n")
    assert call("site", "list", root=root, cwd=project)[0] == 0
    assert info(root, project)["color"] is False


# --- disabled commands ----------------------------------------------------

def test_disabled_command(home):
    root, project = home
    write(project / "appctl.yml", "disabled_commands:\n  - site delete\n  - cache\n")
    code, out, err = call("site", "rm", "x", "--yes", root=root, cwd=project)
    assert (code, out, err) == (1, "", "Error: The 'site delete' command has been disabled.\n")
    assert call("cache", "flush", root=root, cwd=project)[2] == \
        "Error: The 'cache' command has been disabled.\n"
    assert call("site", "list", root=root, cwd=project)[0] == 0


# --- aliases --------------------------------------------------------------

ALIASES = """
"@staging":
  ssh: ssh://deploy@staging.example.com
"@beta":
  path: relative/beta
"@Alpha":
  url: alpha.example.com
"@deploy-all":
  - "@staging"
  - "@nonexistent"
"@pair":
  - "@beta"
  - "@Alpha"
  - "@beta"
"""


def test_all_without_aliases(home):
    root, project = home
    assert call("@all", "site", "list", root=root, cwd=project) == (
        1, "", "Error: Cannot use '@all' when no aliases are registered.\n")


def test_group_with_invalid_member(home):
    root, project = home
    write(project / "appctl.yml", ALIASES)
    assert call("@deploy-all", "site", "list", root=root, cwd=project) == (
        1, "", "Error: Group '@deploy-all' contains one or more invalid "
               "aliases: @nonexistent.\n")


def test_unknown_alias_with_and_without_suggestion(home):
    root, project = home
    write(project / "appctl.yml", ALIASES)
    assert call("@stagin", "site", "list", root=root, cwd=project)[2] == (
        "Error: Alias '@stagin' not found.\nDid you mean '@staging'?\n")
    assert call("@zzzzzzz", "site", "list", root=root, cwd=project)[2] == (
        "Error: Alias '@zzzzzzz' not found.\n")


def test_local_alias_path_absolutized(home):
    root, project = home
    write(project / "appctl.yml", ALIASES)
    code, out, _ = call("@beta", "cli", "info", "--format=json", root=root, cwd=project)
    assert json.loads(out)["path"] == str(project / "relative" / "beta")


def test_group_runs_each_member_once_in_order(home):
    root, project = home
    write(project / "appctl.yml", ALIASES)
    code, out, _ = call("@pair", "cli", "info", "--format=json", root=root, cwd=project)
    lines = out.splitlines()
    assert code == 0 and lines[0] == "@beta" and lines[2] == "@Alpha" and len(lines) == 4
    assert json.loads(lines[3])["url"] == "alpha.example.com"


def test_all_runs_in_case_insensitive_order(home):
    root, project = home
    write(project / "appctl.yml", '"@b": {url: b}\n"@A": {url: a}\n"@c": {url: c}\n')
    code, out, _ = call("@all", "cli", "info", "--format=json", root=root, cwd=project)
    assert [l for l in out.splitlines() if l.startswith("@")] == ["@A", "@b", "@c"]


def test_runtime_alias_overrides_file_alias(home):
    root, project = home
    write(project / "appctl.yml", ALIASES)
    env = {"APPCTL_RUNTIME_ALIAS": json.dumps({"@Alpha": {"url": "rt"}})}
    code, out, _ = call("@Alpha", "cli", "info", "--format=json",
                        root=root, cwd=project, env=env)
    assert json.loads(out)["url"] == "rt"


def _fake_ssh(tmp_path, exit_code):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    script = bindir / "ssh"
    script.write_text('#!/bin/sh\nfor a in "$@"; do echo "$a"; done\n'
                      f"exit {exit_code}\n")
    script.chmod(0o755)
    return str(bindir) + os.pathsep + os.environ.get("PATH", "")


def test_remote_execution_with_pre_command(home, tmp_path):
    root, project = home
    write(project / "appctl.yml", ALIASES)
    env = {"PATH": _fake_ssh(tmp_path, 0), "APPCTL_SSH_PRE_CMD": "echo hi"}
    code, out, err = call("@staging", "site", "list", root=root, cwd=project, env=env)
    assert code == 0 and err == ""
    lines = out.splitlines()
    assert "deploy@staging.example.com" in lines
    assert lines[-1] == "echo hi; appctl site list"


def test_remote_connection_failure(home, tmp_path):
    root, project = home
    write(project / "appctl.yml", ALIASES)
    env = {"PATH": _fake_ssh(tmp_path, 255)}
    code, _, err = call("@staging", "site", "list", root=root, cwd=project, env=env)
    assert code == 255
    assert err == "Error: Cannot connect over SSH using provided configuration.\n"


def test_subprocess_alias_error(tmp_path):
    env = dict(os.environ, APPCTL_ROOT_DIR=str(tmp_path / "root"))
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "appctl.py"),
                           "@all", "site", "list"],
                          capture_output=True, text=True, env=env, cwd=tmp_path)
    assert proc.returncode == 1 and proc.stdout == ""
    assert proc.stderr == "Error: Cannot use '@all' when no aliases are registered.\n"


# --- fallback YAML parser ---------------------------------------------------

def test_fallback_parser_matches_expected():
    text = ('# c\n"@a":\n  ssh: ssh://u@h:22/p  # x\n"@g":\n- "@a"\n'
            "_: {inherit: base.yml, merge: true}\nlist: [a, 'b c']\nflag: yes\n")
    assert yaml_lite._Parser(text).parse() == {
        "@a": {"ssh": "ssh://u@h:22/p"}, "@g": ["@a"],
        "_": {"inherit": "base.yml", "merge": True},
        "list": ["a", "b c"], "flag": True}
