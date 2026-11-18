"""Configuration files, aliases and remote execution."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

from appctl_cli.config_loader import load_config_file
from appctl_cli.remote import parse_ssh_url
from appctl_cli.runtime_config import build_runtime_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "appctl.py")

FAKE_SSH = """#!/bin/sh
for a in "$@"; do echo "ARG[$a]"; done
exit ${FAKE_SSH_EXIT:-0}
"""


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.project = self.mkdir("project")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("APPCTL_")}
        self.env["APPCTL_ROOT_DIR"] = self.mkdir("root")

    def tearDown(self):
        self.tmp.cleanup()

    def mkdir(self, *parts):
        path = os.path.join(self.dir, *parts)
        os.makedirs(path, exist_ok=True)
        return path

    def write(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(content))
        return path

    def run_cli(self, *args, cwd=None, **env):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                              cwd=cwd or self.project, env=dict(self.env, **env))

    def runtime(self, *args, **kwargs):
        result = self.run_cli(*args, "cli", "info", "--format=json", **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["runtime_config"]


class ConfigLoadingTest(ConfigTestCase):
    def test_global_config_is_auto_created(self):
        self.run_cli("cli", "version")
        path = os.path.join(self.env["APPCTL_ROOT_DIR"], "config", "config.yml")
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "locale: en_US\ninstaller_version: stable\n")

    def test_auto_creation_keeps_existing_values(self):
        path = self.write(os.path.join(self.dir, "global.yml"), "locale: fr_FR\n")
        self.run_cli("cli", "version", APPCTL_CONFIG_PATH=path)
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "locale: fr_FR\ninstaller_version: stable\n")

    def test_unwritable_global_config(self):
        blocker = self.write(os.path.join(self.dir, "file"), "")
        result = self.run_cli("site", "list", APPCTL_CONFIG_PATH=os.path.join(blocker, "c.yml"))
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.startswith("Error: "))

    def test_precedence(self):
        path = self.write(os.path.join(self.dir, "global.yml"),
                          "color: false\nurl: global.test\nuser: admin\n")
        self.write(os.path.join(self.project, "appctl.yml"), "url: project.test\n")
        config = self.runtime(APPCTL_CONFIG_PATH=path)
        self.assertEqual((config["color"], config["url"], config["user"]),
                         (False, "project.test", "admin"))
        config = self.runtime("--url=cli.test", "--color", APPCTL_CONFIG_PATH=path)
        self.assertEqual((config["color"], config["url"]), (True, "cli.test"))

    def test_project_config_search(self):
        self.write(os.path.join(self.project, "appctl.yml"), "url: outer\n")
        inner = self.mkdir("project", "inner", "deep")
        self.assertEqual(self.runtime(cwd=inner)["url"], "outer")
        self.write(os.path.join(self.project, "inner", "appctl.yml"), "url: inner\n")
        self.assertEqual(self.runtime(cwd=inner)["url"], "inner")
        self.write(os.path.join(self.project, "inner", "appctl.local.yml"), "url: local\n")
        self.assertEqual(self.runtime(cwd=inner)["url"], "local")

    def test_runtime_only_and_file_only_parameters(self):
        self.write(os.path.join(self.project, "appctl.yml"), "quiet: true\nlocale: fr_FR\n")
        config = self.runtime()
        self.assertNotIn("quiet", config)
        self.assertEqual(config["locale"], "fr_FR")
        result = self.run_cli("config", "create", "--dbname=a", "--dbuser=b", "--locale=xx")
        self.assertIn("locale: xx", result.stdout)

    def test_inherit_and_merge(self):
        base = self.write(os.path.join(self.dir, "base", "base.yml"),
                          "disabled_commands: [a]\nlocale: de_DE\nurl: base\n")
        child = self.write(os.path.join(self.dir, "child.yml"),
                           "_:\n  inherit: base/base.yml\ndisabled_commands: [b]\nurl: child\n")
        self.assertEqual(load_config_file(child),
                         {"disabled_commands": ["b"], "locale": "de_DE", "url": "child"})
        self.write(child, "_:\n  inherit: base/base.yml\n  merge: true\ndisabled_commands: [b, a]\n")
        self.assertEqual(load_config_file(child)["disabled_commands"], ["a", "b", "a"])
        self.assertTrue(os.path.isfile(base))

    def test_disabled_commands(self):
        self.write(os.path.join(self.project, "appctl.yml"), "disabled_commands:\n  - site delete\n  - db\n")
        result = self.run_cli("site", "delete", "main", "--yes")
        self.assertEqual((result.returncode, result.stderr),
                         (1, "Error: The 'site delete' command has been disabled.\n"))
        result = self.run_cli("db", "query", "SELECT 1")
        self.assertEqual(result.stderr, "Error: The 'db' command has been disabled.\n")
        self.assertEqual(self.run_cli("site", "list").returncode, 0)

    def test_build_runtime_config_ignores_non_file_layers(self):
        config = build_runtime_config({"quiet": True}, {"debug": True, "locale": "x"})
        self.assertEqual((config["debug"], config["quiet"], config["locale"]), (False, True, "x"))


class AliasTest(ConfigTestCase):
    CONFIG = """\
        "@staging":
          ssh: ssh://deploy@staging.example.com:2222/var/www
        "@deploy-all":
          - "@staging"
          - "@nonexistent"
        "@Beta":
          path: sites/beta
        "@alpha":
          path: /srv/alpha
        "@pair":
          - "@alpha"
          - "@Beta"
          - "@alpha"
        """

    def setUp(self):
        super().setUp()
        bin_dir = self.mkdir("bin")
        ssh = self.write(os.path.join(bin_dir, "ssh"), FAKE_SSH)
        os.chmod(ssh, os.stat(ssh).st_mode | stat.S_IEXEC)
        self.env["PATH"] = bin_dir + os.pathsep + self.env.get("PATH", "")

    def configure(self):
        self.write(os.path.join(self.project, "appctl.yml"), self.CONFIG)

    def test_all_without_aliases(self):
        result = self.run_cli("@all", "site", "list")
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, "", "Error: Cannot use '@all' when no aliases are registered.\n"))

    def test_invalid_group(self):
        self.configure()
        result = self.run_cli("@deploy-all", "site", "list")
        self.assertEqual((result.returncode, result.stderr), (1, (
            "Error: Group '@deploy-all' contains one or more invalid aliases: @nonexistent.\n")))

    def test_unknown_alias(self):
        self.configure()
        result = self.run_cli("@stagign", "site", "list")
        self.assertEqual((result.returncode, result.stderr), (1, (
            "Error: Alias '@stagign' not found.\nDid you mean '@staging'?\n")))
        result = self.run_cli("@qqqqqqq", "site", "list")
        self.assertEqual(result.stderr, "Error: Alias '@qqqqqqq' not found.\n")

    def test_local_path_is_absolutized(self):
        self.configure()
        result = self.run_cli("@Beta", "config", "path", cwd=self.mkdir("project", "nested"))
        expected = os.path.join(self.project, "sites", "beta", "config.php")
        self.assertEqual(result.stdout, expected + "\n")

    def test_group_runs_each_member_once(self):
        self.configure()
        result = self.run_cli("@pair", "config", "path")
        beta = os.path.join(self.project, "sites", "beta", "config.php")
        self.assertEqual(result.stdout, f"@alpha\n/srv/alpha/config.php\n@Beta\n{beta}\n")

    def test_all_runs_in_case_insensitive_order(self):
        self.configure()
        result = self.run_cli("@all", "config", "path")
        headers = [line for line in result.stdout.splitlines() if line.startswith("@")]
        self.assertEqual(headers, ["@alpha", "@Beta", "@staging"])

    def test_runtime_alias_overrides_file_alias(self):
        self.configure()
        result = self.run_cli("@alpha", "config", "path",
                              APPCTL_RUNTIME_ALIAS=json.dumps({"@alpha": {"path": "/rt"}}))
        self.assertEqual(result.stdout, "/rt/config.php\n")

    def test_remote_execution(self):
        self.configure()
        result = self.run_cli("@staging", "site", "list", APPCTL_SSH_PRE_CMD="cd /tmp")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, (
            "ARG[-q]\nARG[-p]\nARG[2222]\nARG[-T]\nARG[deploy@staging.example.com]\n"
            "ARG[cd /tmp; appctl site list --path=/var/www]\n"))

    def test_ssh_connection_failure(self):
        self.configure()
        result = self.run_cli("@staging", "site", "list", FAKE_SSH_EXIT="255")
        self.assertEqual(result.returncode, 255)
        self.assertTrue(result.stderr.endswith(
            "Error: Cannot connect over SSH using provided configuration.\n"))

    def test_parse_ssh_url(self):
        self.assertEqual(parse_ssh_url("docker:user@app"),
                         {"scheme": "docker", "user": "user", "host": "app"})
        self.assertEqual(parse_ssh_url("example.com:22~/www"),
                         {"host": "example.com", "port": "22", "path": "~/www"})


if __name__ == "__main__":
    unittest.main()
