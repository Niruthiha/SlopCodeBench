"""End-to-end tests running appctl.py as a subprocess."""

import os
import re
import subprocess
import sys
import tempfile
import unittest

from tests.helpers import initialize, runtime_env

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "appctl.py")
_home = None


def setUpModule():
    global _home
    _home = tempfile.TemporaryDirectory()
    initialize(environment())


def tearDownModule():
    _home.cleanup()


def environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith("APPCTL_")}
    return runtime_env(env, APPCTL_ROOT_DIR=_home.name)


def run(*args, strict=False):
    env = environment()
    if strict:
        env["APPCTL_STRICT_ARGS_MODE"] = "1"
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                          env=env, cwd=ROOT)


class CliTest(unittest.TestCase):
    def test_no_arguments_lists_commands_sorted_and_aligned(self):
        result = run()
        self.assertEqual(result.returncode, 0)
        rows = [m for m in re.finditer(r"^  (\S+)( +)(\S.*)$", result.stdout, re.M)]
        names = [m.group(1) for m in rows]
        self.assertIn("site", names)
        self.assertEqual(names, sorted(names, key=str.lower))
        columns = {len(m.group(1)) + len(m.group(2)) for m in rows}
        self.assertEqual(len(columns), 1)

    def test_unknown_command(self):
        result = run("sitee")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, (
            "Error: 'sitee' is not a registered appctl command. "
            "See 'appctl help' for available commands.\nDid you mean 'site'?\n"))
        self.assertEqual(result.stdout, "")

    def test_unknown_command_without_suggestion(self):
        result = run("qqqqqq")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Did you mean", result.stderr)

    def test_unknown_subcommand(self):
        result = run("site", "craete")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, (
            "Error: 'craete' is not a registered subcommand of 'site'. "
            "See 'appctl help site' for available subcommands.\nDid you mean 'create'?\n"))

    def test_synonym_suggestion(self):
        self.assertIn("Did you mean 'create'?", run("site", "new").stderr)

    def test_alias_wins_over_synonym(self):
        result = run("user", "remove", "2")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Did you mean", result.stderr)
        self.assertIn("Removed user 2", result.stdout)

    def test_parent_without_handler_prints_usage(self):
        result = run("site")
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage: appctl site activate", result.stdout)
        self.assertIn("   or: appctl site create", result.stdout)

    def test_missing_positional_prints_usage(self):
        result = run("site", "create")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.startswith("usage: appctl site create <site-name>"))

    def test_too_many_positionals(self):
        result = run("site", "create", "a", "b")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "Error: Too many positional arguments: b\n")

    def test_missing_required_assoc(self):
        result = run("config", "create", "--dbname=x", "--dbuser=")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "Error: Parameter errors:\n missing --dbuser parameter\n")

    def test_unknown_assoc_with_suggestion(self):
        result = run("site", "create", "x", "--typ=a", "--bogus")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, (
            "Error: Parameter errors:\n unknown --typ parameter\nDid you mean '--type'?\n"
            " unknown --bogus parameter\n"))

    def test_defaults_applied(self):
        result = run("site", "create", "x")
        self.assertEqual(result.returncode, 0)
        self.assertIn("type: standard", result.stdout)

    def test_no_prefix_sets_false(self):
        self.assertIn("visibility: public", run("site", "create", "x", "--no-private").stdout)
        self.assertIn("visibility: private", run("site", "create", "x", "--private").stdout)

    def test_help_rewrite(self):
        self.assertEqual(run("site", "create", "--help").stdout, run("help", "site", "create").stdout)
        self.assertIn("SYNOPSIS", run("site", "create", "--help").stdout)

    def test_version_rewrite(self):
        result = run("--version")
        self.assertEqual((result.returncode, result.stdout), (0, run("cli", "version").stdout))

    def test_strict_mode(self):
        self.assertEqual(run("site", "create", "x", "--url=a").returncode, 0)
        strict = run("site", "create", "x", "--url=a", strict=True)
        self.assertEqual(strict.returncode, 1)
        self.assertIn("unknown --url parameter", strict.stderr)
        self.assertEqual(run("--url=a", "site", "create", "x", strict=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
