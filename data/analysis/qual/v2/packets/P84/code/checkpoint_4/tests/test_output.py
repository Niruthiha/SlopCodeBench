"""Output formats, message categories, logging and user interaction."""

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

import yaml

from appctl_cli.errors import AppctlError
from appctl_cli.formatter import format_items, resolve_field, select_fields
from appctl_cli.logger import FileLogger, redact_argv
from appctl_cli.output import Output

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "appctl.py")
TIMESTAMP = r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\]"


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("APPCTL_")}
        self.env["APPCTL_ROOT_DIR"] = self.tmp.name
        self.log_path = os.path.join(self.tmp.name, "logs", "appctl.log")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, input=""):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                              input=input, env=self.env, cwd=self.tmp.name)

    def read_log(self):
        with open(self.log_path, encoding="utf-8") as handle:
            return handle.read()


class FormatTest(CliTestCase):
    def test_json_is_pretty_and_ordered(self):
        result = self.run_cli("site", "list", "--format=json", "--fields=url,name")
        self.assertIn('\n    {\n        "url": ', result.stdout)
        self.assertEqual(list(json.loads(result.stdout)[0]), ["url", "name"])

    def test_yaml_block_style(self):
        result = self.run_cli("site", "list", "--format=yaml")
        self.assertIn("- name: blog\n  type: blog\n", result.stdout)
        self.assertEqual(yaml.safe_load(result.stdout)[2]["status"], "archived")

    def test_count_and_ids(self):
        self.assertEqual(self.run_cli("post", "list", "--format=count").stdout, "3\n")
        self.assertEqual(self.run_cli("post", "list", "--format=ids").stdout, "1 2 3\n")

    def test_csv_follows_fields_order(self):
        result = self.run_cli("site", "list", "--format=csv", "--fields=status,name")
        self.assertEqual(result.stdout.splitlines()[:2], ["status,name", "active,blog"])

    def test_table_widths_and_order(self):
        lines = self.run_cli("site", "list", "--fields=url,name").stdout.splitlines()
        self.assertEqual(lines[1], "| url                       | name |")

    def test_single_item_is_vertical(self):
        result = self.run_cli("site", "list", "--status=archived")
        self.assertIn("| Field  | Value                     |", result.stdout)
        self.assertIn("| status | archived                  |", result.stdout)

    def test_field_prefix_and_case_insensitive_fields(self):
        self.assertEqual(self.run_cli("post", "get", "1", "--field=title").stdout, "Hello world!\n")
        result = self.run_cli("post", "list", "--format=csv", "--fields=TITLE,id")
        self.assertEqual(result.stdout.splitlines()[0], "post_title,ID")

    def test_invalid_field(self):
        result = self.run_cli("site", "list", "--fields=name,bogus")
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, "", "Error: Invalid field: bogus.\n"))
        self.assertEqual(self.run_cli("site", "list", "--field=nope").stderr,
                         "Error: Invalid field: nope.\n")

    def test_complex_values_serialized_as_json(self):
        items = [{"id": 1, "tags": ["a", "b"], "meta": {"k": "v"}}, {"id": 2, "tags": [], "meta": {}}]
        table = format_items(items, ["id", "tags", "meta"])
        self.assertIn('| 1  | ["a", "b"] | {"k": "v"} |', table)
        csv_text = format_items(items, ["tags"], "csv")
        self.assertEqual(csv_text, 'tags\n"[""a"", ""b""]"\n[]')

    def test_resolve_field(self):
        self.assertEqual(resolve_field("id", ["ID", "post_title"]), "ID")
        self.assertEqual(resolve_field("Title", ["ID", "post_title"], prefix="post"), "post_title")
        self.assertEqual(select_fields("b, a", ["a"], ["a", "b"]), ["b", "a"])
        with self.assertRaises(AppctlError):
            resolve_field("x", ["a"])


class ColorTest(CliTestCase):
    def test_piped_output_is_plain(self):
        result = self.run_cli("site", "create", "Bad")
        self.assertTrue(result.stderr.startswith("Error: Invalid site name"))

    def test_forced_color(self):
        result = self.run_cli("--color", "site", "create", "Bad")
        self.assertTrue(result.stderr.startswith("\033[1;31mError:\033[0m Invalid site name"))
        result = self.run_cli("--color", "db", "drop", "--yes")
        self.assertEqual(result.stdout, "\033[1;32mSuccess:\033[0m Database 'appctl' dropped.\n")

    def test_no_color_and_config(self):
        os.makedirs(os.path.join(self.tmp.name, "config"))
        with open(os.path.join(self.tmp.name, "config", "config.yml"), "w") as handle:
            handle.write("color: true\n")
        self.assertIn("\033[", self.run_cli("site", "create", "Bad").stderr)
        self.assertEqual(self.run_cli("--no-color", "site", "create", "Bad").stderr[:6], "Error:")

    def test_distinct_prefix_colors(self):
        out = io.StringIO()
        output = Output(stdout=out, stderr=out, color=True, debug=True)
        output.error("e")
        output.warning("w")
        output.success("s")
        output.debug("d")
        codes = re.findall(r"(\033\[[0-9;]+m)(Error|Warning|Success|Debug):", out.getvalue())
        self.assertEqual([c[1] for c in codes], ["Error", "Warning", "Success", "Debug"])
        self.assertEqual(len({c[0] for c in codes}), 4)

    def test_multi_line_error_box(self):
        err = io.StringIO()
        Output(stderr=err, color=False).error_multi_line(["one", "two three"])
        self.assertEqual(err.getvalue(), (
            "+------------------+\n"
            "| Error: one       |\n"
            "|        two three |\n"
            "+------------------+\n"))


class MessageTest(CliTestCase):
    def test_debug_output(self):
        result = self.run_cli("--debug", "site", "list", "--format=count")
        self.assertRegex(result.stderr, r"Debug: Running command: site list \(\d+\.\d{3}s\)\n")
        self.assertIn("Debug (bootstrap):", result.stderr)
        self.assertEqual(result.stdout, "3\n")
        self.assertIn("Debug: Running command: site list", self.read_log())

    def test_debug_group(self):
        result = self.run_cli("--debug=bootstrap", "site", "list", "--format=count")
        lines = result.stderr.splitlines()
        self.assertTrue(lines)
        self.assertTrue(all(line.startswith("Debug (bootstrap): ") for line in lines))
        self.assertEqual(self.run_cli("--debug=nothing", "site", "list").stderr, "")

    def test_quiet(self):
        result = self.run_cli("--quiet", "plugin", "activate", "akismet")
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_log_file(self):
        self.run_cli("plugin", "activate", "akismet", "nope")
        self.run_cli("db", "drop", "--yes")
        log = self.read_log()
        delimiters = [line for line in log.splitlines() if re.fullmatch(r"-{20,}", line)]
        self.assertEqual(len(delimiters), 2)
        for line in log.splitlines():
            if line not in delimiters:
                self.assertRegex(line, "^" + TIMESTAMP + " ")
        self.assertIn("Command: appctl plugin activate akismet nope", log)
        self.assertIn("] Plugin 'akismet' activated.\n", log)
        self.assertIn("] Warning: The 'nope' plugin could not be found.\n", log)
        self.assertIn("] Error: Only activated 1 of 2 plugins.\n", log)
        self.assertNotIn("Success", log)

    def test_completion_is_not_logged(self):
        result = self.run_cli("cli", "completions", "--line=appctl site cr", "--point=100")
        self.assertEqual(result.stdout, "create \n")
        self.assertFalse(os.path.exists(self.log_path))

    def test_sensitive_material_not_logged(self):
        result = self.run_cli("option", "add", "k", "--format=json", input="{secret-token\n")
        self.assertEqual((result.returncode, result.stderr),
                         (1, "Error: Invalid JSON: {secret-token\n"))
        self.run_cli("user", "create", "bob", "bob@example.test", "--user_pass=hunter2")
        log = self.read_log()
        self.assertNotIn("secret-token", log)
        self.assertNotIn("hunter2", log)

    def test_sensitive_info(self):
        out = io.StringIO()
        logger = FileLogger(self.log_path)
        Output(stdout=out, logger=logger).log("Password: hunter2", sensitive=True)
        Output(stdout=out, logger=logger, quiet=True).log("quiet hunter2", sensitive=True)
        Output(stderr=out, logger=logger).error("bad hunter2", sensitive=True)
        self.assertEqual(out.getvalue(), "Password: hunter2\nError: bad hunter2\n")
        self.assertFalse(os.path.exists(self.log_path))

    def test_redact_argv(self):
        self.assertEqual(redact_argv(["x", "--dbpass=s", "--name=n", "--", "--token=t"]),
                         ["x", "--dbpass=[REDACTED]", "--name=n", "--", "--token=t"])


class InteractionTest(CliTestCase):
    def test_confirmation_cancelled(self):
        for answer in ("n\n", "yes\n", "\n", ""):
            result = self.run_cli("db", "drop", input=answer)
            self.assertEqual(result.stdout, "Are you sure you want to drop the 'appctl' database? [y/n] ")
            self.assertEqual(result.stderr, "Warning: Operation cancelled.\n")

    def test_confirmation_accepted(self):
        result = self.run_cli("site", "delete", "main", input="  Y \n")
        self.assertTrue(result.stdout.endswith("Success: The site 'main' was deleted.\n"))
        result = self.run_cli("db", "reset", "--yes", input="n\n")
        self.assertEqual(result.stdout, "Success: Database 'appctl' reset.\n")

    def test_prompt_normalizes(self):
        out = io.StringIO()
        output = Output(stdout=out, stdin=io.StringIO("  MiXeD Case \nnext\n"))
        self.assertEqual(output.prompt("Q? "), "mixed case")
        self.assertEqual(out.getvalue(), "Q? ")

    def test_positional_from_stdin(self):
        result = self.run_cli("site", "create", input="fresh\n")
        self.assertIn("Site 'fresh' created", result.stdout)
        result = self.run_cli("option", "add", "k", "--format=json", input='{"a": 1}')
        self.assertEqual((result.returncode, result.stdout),
                         (0, "Success: Added 'k' option (autoload: yes).\n"))

    def test_missing_positional_without_stdin(self):
        result = self.run_cli("site", "create")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.startswith("usage: appctl site create"))


if __name__ == "__main__":
    unittest.main()
