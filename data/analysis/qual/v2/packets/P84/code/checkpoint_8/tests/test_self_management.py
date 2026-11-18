"""System requirements, first run, version checks, self-update, cli commands and completion."""

import io
import json
import os
import pprint
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

import yaml

from appctl_cli import __version__, container, database, self_update, startup, system, upgrade
from appctl_cli.errors import AppctlError
from appctl_cli.file_cache import reset_cache
from appctl_cli.output import Output
from build_archive import build

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "appctl.py")

# Logs every call; FAKE_PS_FAIL makes the responsiveness probe fail; FAKE_IDS_<KIND>
# lists the ids returned for labeled resources.
FAKE_DOCKER = textwrap.dedent("""\
    #!/bin/sh
    [ -n "$FAKE_DOCKER_LOG" ] && echo "$*" >> "$FAKE_DOCKER_LOG"
    case "$*" in
      "ps -q") [ -n "$FAKE_PS_FAIL" ] && exit 1; exit 0 ;;
      "compose version"*)
        [ -n "$FAKE_NO_COMPOSE" ] && exit 1
        echo "${FAKE_COMPOSE_VERSION:-2.29.7}"; exit 0 ;;
      "ps -aq --filter"*) printf "%s" "$FAKE_IDS_CONTAINERS" ;;
      "network ls -q --filter"*) printf "%s" "$FAKE_IDS_NETWORKS" ;;
      "volume ls -q --filter"*) printf "%s" "$FAKE_IDS_VOLUMES" ;;
      "images -q --filter"*) printf "%s" "$FAKE_IDS_IMAGES" ;;
    esac
    exit 0
""")

MIGRATION = textwrap.dedent("""\
    def up(ctx):
        with open(ctx.environ["MIG_LOG"], "a") as handle:
            handle.write(ctx.name + "\\n")
""")


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    if mode:
        os.chmod(path, mode)
    return path


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = os.path.join(self.tmp, "bin")
        write(os.path.join(self.bin, "docker"), FAKE_DOCKER, 0o755)
        self.root = os.path.join(self.tmp, "root")
        self.docker_log = os.path.join(self.tmp, "docker.log")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("APPCTL_", "FAKE_"))}
        self.env.update({
            "PATH": self.bin + os.pathsep + "/bin:/usr/bin",
            "HOME": self.tmp,
            "APPCTL_ROOT_DIR": self.root,
            "APPCTL_PACKAGES_DIR": os.path.join(self.tmp, "packages"),
            "FAKE_DOCKER_LOG": self.docker_log,
        })
        self.addCleanup(database.close_all)
        self.addCleanup(container._compose_binary.clear)
        self.addCleanup(reset_cache)

    def cli(self, *args, input="", script=SCRIPT, **env):
        database.close_all()
        return subprocess.run([sys.executable, script, *args], capture_output=True, text=True,
                              input=input, env=dict(self.env, **env), cwd=self.tmp)

    def init(self):
        result = self.cli("cli", "version")
        self.assertEqual(result.returncode, 0, result.stderr)

    def docker_calls(self):
        return read(self.docker_log).splitlines() if os.path.exists(self.docker_log) else []

    def set_stored_version(self, version):
        connection = sqlite3.connect(database.db_path(self.env))
        with connection:
            connection.execute('UPDATE options SET value = ? WHERE "key" = ?', (version, "version"))
        connection.close()

    def stored_version(self):
        connection = sqlite3.connect(database.db_path(self.env))
        row = connection.execute('SELECT value FROM options WHERE "key" = ?',
                                 ("version",)).fetchone()
        connection.close()
        return row and row[0]

    def output(self):
        self.out, self.err = io.StringIO(), io.StringIO()
        return Output(stdout=self.out, stderr=self.err, stdin=io.StringIO())


# -- system requirements ---------------------------------------------------------------------


class RequirementsTest(Case):
    def test_all_met(self):
        self.init()
        result = self.cli("site", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ps -q", self.docker_calls())

    def test_runtime_down_retries_with_backoff(self):
        self.init()
        started = time.monotonic()
        result = self.cli("site", "list", FAKE_PS_FAIL="1")
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("Error: Container runtime is either not installed or not running.",
                      result.stderr)
        self.assertNotIn("brew", result.stderr)
        self.assertEqual(self.docker_calls().count("ps -q"), system.RUNTIME_CHECK_ATTEMPTS)
        self.assertGreaterEqual(elapsed, system.RUNTIME_CHECK_BACKOFF * 3)

    def test_backoff_doubles_and_is_bounded(self):
        sleeps = []
        with mock.patch.object(system, "run_command") as run:
            run.return_value.succeeded = False
            self.assertFalse(system.runtime_responsive(sleep=sleeps.append))
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleeps, [0.5, 1.0])

    def test_runtime_recovers_on_retry(self):
        results = iter([False, True])
        sleeps = []
        with mock.patch.object(system, "run_command") as run:
            run.side_effect = lambda *a, **k: mock.Mock(succeeded=next(results))
            self.assertTrue(system.runtime_responsive(sleep=sleeps.append))
        self.assertEqual(sleeps, [0.5])

    def test_darwin_hint(self):
        self.assertIn("brew", system.runtime_error("Darwin"))
        self.assertNotIn("brew", system.runtime_error("Linux"))
        with mock.patch.object(system, "runtime_responsive", return_value=False), \
                mock.patch.object(system, "compose_errors", return_value=[]), \
                mock.patch.object(system, "runtime_version_errors", return_value=[]):
            with self.assertRaises(AppctlError) as ctx:
                system.ensure_requirements({}, self.output(), platform_name="Darwin")
        self.assertIn("system package manager", ctx.exception.message)
        self.assertIn("brew install", ctx.exception.message)

    def test_compose_missing(self):
        self.init()
        # Only a shell besides the fake runtime: no legacy compose binary either.
        tools = os.path.join(self.tmp, "tools")
        os.makedirs(tools)
        os.symlink("/bin/sh", os.path.join(tools, "sh"))
        result = self.cli("site", "list", FAKE_NO_COMPOSE="1",
                          PATH=self.bin + os.pathsep + tools)
        self.assertEqual(result.returncode, 1)
        self.assertIn("requires the compose tool", result.stderr)

    def test_compose_too_old(self):
        self.init()
        result = self.cli("site", "list", FAKE_COMPOSE_VERSION="2.26.1-4")
        self.assertEqual(result.returncode, 1)
        self.assertIn("compose tool version 2.27.0 or greater (installed: 2.26.1-4)", result.stderr)
        self.assertEqual(self.cli("site", "list", FAKE_COMPOSE_VERSION="2.100.0").returncode, 0)

    def test_runtime_too_old(self):
        self.init()
        fake = write(os.path.join(self.tmp, "oldpython"), "#!/bin/sh\necho Python 3.6.9\n", 0o755)
        result = self.cli("site", "list", APPCTL_RUNTIME_BIN=fake)
        self.assertEqual(result.returncode, 1)
        self.assertIn("requires Python 3.8.0 or greater (current: 3.6.9)", result.stderr)

    def test_every_problem_reported(self):
        self.init()
        result = self.cli("site", "list", FAKE_PS_FAIL="1", FAKE_NO_COMPOSE="1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.count("Error: "), 2)

    def test_exempt_families(self):
        self.init()
        for args in (("cli", "info"), ("config", "path"), ("help",), ("help", "site"), ()):
            result = self.cli(*args, FAKE_PS_FAIL="1", FAKE_NO_COMPOSE="1")
            self.assertEqual(result.returncode, 0, (args, result.stderr))
        self.assertNotIn("ps -q", self.docker_calls())

    def test_command_alias_is_not_exempt(self):
        self.init()
        self.assertEqual(self.cli("cfg", "path", FAKE_PS_FAIL="1").returncode, 0)  # config
        self.assertEqual(self.cli("user", "list", FAKE_NO_COMPOSE="1").returncode, 1)


class RuntimeBinaryTest(unittest.TestCase):
    def test_precedence(self):
        env = {"APPCTL_RUNTIME_BIN": "/opt/a", "APPCTL_RUNTIME_BIN_USED": "/opt/b"}
        self.assertEqual(system.runtime_binary(env), "/opt/a")
        self.assertEqual(system.runtime_binary({"APPCTL_RUNTIME_BIN_USED": "/opt/b"}), "/opt/b")
        self.assertEqual(system.runtime_binary({"APPCTL_RUNTIME_BIN": " "}), sys.executable)
        with mock.patch.object(system.sys, "executable", ""):
            self.assertEqual(system.runtime_binary({}), "python3")

    def test_child_processes_record_the_binary(self):
        from appctl_cli.process import self_command, self_environment
        env = self_environment(environ={"APPCTL_RUNTIME_BIN": "/opt/py"})
        self.assertEqual(env["APPCTL_RUNTIME_BIN_USED"], "/opt/py")
        self.assertEqual(self_command("cli info")[0], sys.executable)


# -- first run and version checks ----------------------------------------------------------


class FirstRunTest(Case):
    def setUp(self):
        super().setUp()
        self.core = os.path.join(self.tmp, "core")
        write(os.path.join(self.core, "migrations", "db", "1_first.py"), MIGRATION)
        write(os.path.join(self.core, "migrations", "container", "2_second.py"), MIGRATION)
        self.mig_log = os.path.join(self.tmp, "mig.log")
        self.env["MIG_LOG"] = self.mig_log

    def migrations_run(self):
        return read(self.mig_log).splitlines() if os.path.exists(self.mig_log) else []

    def test_setup_runs_migrations_and_reports(self):
        output = self.output()
        with mock.patch.dict(os.environ, self.env), \
                mock.patch.object(upgrade, "CORE_MIGRATIONS_DIR",
                                  os.path.join(self.core, "migrations")):
            db = database.get_db(self.env)
            startup.Startup(self.env, output, db).run()
            self.assertEqual(db.get_option("version"), __version__)
            self.assertEqual(sorted(db.get_migration_names()), ["appctl:1_first",
                                                                "appctl:2_second"])
        self.assertEqual(self.migrations_run(), ["1_first", "2_second"])
        self.assertEqual(self.out.getvalue(), f"Success: {startup.FIRST_RUN_SUCCESS}\n")

    def test_darwin_instructions(self):
        output = self.output()
        db = database.get_db(self.env)
        startup.Startup(self.env, output, db, platform_name="Darwin").run()
        self.assertIn("Docker Desktop", self.out.getvalue())
        self.assertIn(self.root, self.out.getvalue())

    def test_first_run_cli(self):
        self.assertFalse(os.path.exists(database.db_path(self.env)))
        result = self.cli("cli", "info")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("Success: AppCtl has been set up successfully.\n"))
        self.assertEqual(self.stored_version(), __version__)
        self.assertNotIn("set up", self.cli("cli", "info").stdout)

    def test_first_run_preserves_machine_output(self):
        result = self.cli("cli", "version")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, f"{__version__}\n", ""))
        for args in (("cli", "info", "--format=json"), ("cli", "cmd-dump"),
                     ("cli", "param-dump"), ("cli", "alias", "--format=json"),
                     ("site", "list", "--format=json")):
            shutil.rmtree(self.root)
            result = self.cli(*args)
            self.assertEqual(result.returncode, 0, (args, result.stderr))
            json.loads(result.stdout)
            self.assertEqual(self.stored_version(), __version__)

    def test_first_run_silent_commands(self):
        result = self.cli("cli", "has-command", "site list")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        shutil.rmtree(self.root)
        result = self.cli("cli", "completions", "--line=appctl cli ver", "--point=14")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "version \n", ""))


class VersionCheckTest(Case):
    def setUp(self):
        super().setUp()
        self.init()

    def test_older_binary_cli_warns(self):
        self.set_stored_version("99.0.0")
        result = self.cli("cli", "version")
        self.assertEqual((result.returncode, result.stdout), (0, f"{__version__}\n"))
        self.assertTrue(result.stderr.startswith("Warning: "))
        self.assertIn("99.0.0", result.stderr)
        self.assertEqual(self.stored_version(), "99.0.0")

    def test_older_binary_other_commands_fail(self):
        self.set_stored_version("1.10.0")  # semantic, not lexical: 1.10.0 > 1.0.0
        for args in (("site", "list"), ("help",), ("config", "path")):
            result = self.cli(*args)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr.startswith("Error: "))
            self.assertIn("update", result.stderr)

    def test_older_binary_silent_commands(self):
        self.set_stored_version("99.0.0")
        result = self.cli("cli", "has-command", "site")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_newer_binary_migrates(self):
        self.set_stored_version("0.9.0")
        result = self.cli("cli", "version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stored_version(), __version__)

    def test_version_status(self):
        self.assertEqual(upgrade.version_status("0.9.9", "1.0.0"), upgrade.VERSION_NEWER)
        self.assertEqual(upgrade.version_status("1.0.0", "1.0.0"), upgrade.VERSION_CURRENT)
        self.assertEqual(upgrade.version_status("1.0.10", "1.0.9"), upgrade.VERSION_OLDER)
        for stored in ("1.0.0", "2.0.0", "1.0.0-nightly"):
            self.assertEqual(upgrade.version_status(stored, "1.0.0-nightly"),
                             upgrade.VERSION_NEWER)

    def test_nightly_always_migrates(self):
        output = self.output()
        db = database.get_db(self.env)
        with mock.patch.object(upgrade, "run_upgrade") as run:
            startup.Startup(self.env, output, db, current="1.0.0-nightly").run()
            startup.Startup(self.env, output, db, current="1.0.0").run()
        self.assertEqual(run.call_count, 1)


# -- automatic update check ------------------------------------------------------------------


class AutoUpdateTest(Case):
    def setUp(self):
        super().setUp()
        self.updates = []
        patcher = mock.patch.object(self_update, "available_updates",
                                    side_effect=lambda *a, **k: list(self.updates))
        self.available = patcher.start()
        self.addCleanup(patcher.stop)
        self.triggered = mock.Mock(return_value=0)

    def check(self, now, interactive=True, writable=True, **env):
        environ = dict(self.env, **env)
        return self_update.auto_check_update(environ, self.output(), now=now,
                                             interactive=interactive, writable=writable,
                                             update=self.triggered, platform_name="Linux")

    def test_first_check_only_caches(self):
        self.updates = [{"version": "9.0.0"}]
        self.assertIsNone(self.check(1000))
        self.available.assert_not_called()
        self.assertIsNone(self.check(1000 + 86399))  # less than one whole day
        self.available.assert_not_called()
        self.assertEqual(self.check(1000 + 86400), 0)
        self.triggered.assert_called_once()
        self.assertIsNone(self.check(1000 + 86400 + 3600))  # timestamp updated

    def test_no_update_found(self):
        self.check(0)
        self.assertIsNone(self.check(86400 * 3))
        self.available.assert_called_once()
        self.triggered.assert_not_called()

    def test_interval_override(self):
        self.updates = [{"version": "9.0.0"}]
        self.check(0, APPCTL_AUTO_CHECK_UPDATE_DAYS="3")
        self.assertIsNone(self.check(86400 * 2 + 86399, APPCTL_AUTO_CHECK_UPDATE_DAYS="3"))
        self.assertEqual(self.check(86400 * 3, APPCTL_AUTO_CHECK_UPDATE_DAYS="3"), 0)
        self.assertEqual(self_update.check_interval({}), 1)
        self.assertEqual(self_update.check_interval({"APPCTL_AUTO_CHECK_UPDATE_DAYS": "x"}), 1)

    def test_disabled_and_non_interactive(self):
        self.updates = [{"version": "9.0.0"}]
        for kwargs in ({"APPCTL_DISABLE_AUTO_CHECK_UPDATE": "1"}, {"interactive": False},
                       {"writable": False}):
            self.check(0, **kwargs)
            self.assertIsNone(self.check(86400 * 10, **kwargs))
        self.available.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(self.root, ".cache")))

    def test_piped_invocations_never_check(self):
        result = self.cli("cli", "info")
        self.assertEqual(result.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".cache",
                                                     self_update.UPDATE_CHECK_KEY)))


# -- cli commands ------------------------------------------------------------------------------


class InfoTest(Case):
    def setUp(self):
        super().setUp()
        self.init()

    def test_version(self):
        result = self.cli("cli", "version")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, f"{__version__}\n", ""))
        self.assertEqual(self.cli("--version").stdout, f"{__version__}\n")

    def test_list_and_json(self):
        result = self.cli("cli", "info", APPCTL_RUNTIME_BIN="/opt/custom/python", SHELL="/bin/zsh")
        lines = dict(line.split(":\t", 1) for line in result.stdout.splitlines())
        self.assertEqual(lines["Shell"], "/bin/zsh")
        self.assertEqual(lines["Runtime binary"], "/opt/custom/python")
        self.assertEqual(lines["AppCtl root dir"], self.root)
        self.assertEqual(lines["AppCtl packages dir"], "")
        self.assertEqual(lines["AppCtl version"], __version__)
        self.assertIn("OS", lines)
        data = json.loads(self.cli("cli", "info", "--format=json").stdout)
        self.assertIsNone(data["appctl_packages_dir_path"])
        self.assertEqual(data["appctl_version"], __version__)
        self.assertEqual(data["appctl_root_dir"], self.root)
        self.assertEqual(data["global_config_path"],
                         os.path.join(self.root, "config", "config.yml"))
        self.assertEqual(data["runtime_binary"], sys.executable)
        os.makedirs(self.env["APPCTL_PACKAGES_DIR"])
        data = json.loads(self.cli("cli", "info", "--format=json").stdout)
        self.assertEqual(data["appctl_packages_dir_path"], self.env["APPCTL_PACKAGES_DIR"])

    def test_invalid_format(self):
        self.assertEqual(self.cli("cli", "info", "--format=xml").returncode, 1)


class DumpTest(Case):
    def setUp(self):
        super().setUp()
        self.init()

    def test_cmd_dump(self):
        data = json.loads(self.cli("cli", "cmd-dump").stdout)
        self.assertEqual(data["name"], "appctl")
        paths = []

        def walk(entry, prefix):
            for key in ("name", "description", "longdesc", "subcommands"):
                self.assertIn(key, entry)
            if entry["subcommands"]:
                self.assertNotIn("synopsis", entry)
            else:
                self.assertIn("synopsis", entry)
            for sub in entry["subcommands"]:
                paths.append(prefix + [sub["name"]])
                walk(sub, prefix + [sub["name"]])

        walk(data, [])
        self.assertEqual(paths, sorted(paths))
        self.assertIn(["cli", "has-command"], paths)
        cli = next(c for c in data["subcommands"] if c["name"] == "cli")
        info = next(c for c in cli["subcommands"] if c["name"] == "info")
        self.assertEqual(info["synopsis"], "[--format=<format>]")

    def test_param_dump(self):
        data = json.loads(self.cli("cli", "param-dump").stdout)
        self.assertEqual(list(data), sorted(data))
        self.assertNotIn("current", data["url"])
        self.assertEqual(data["url"]["synopsis"], "--url=<url>")
        data = json.loads(self.cli("cli", "param-dump", "--with-values", "--url=x.test").stdout)
        self.assertEqual(data["url"]["current"], "x.test")
        self.assertEqual(data["color"]["current"], "auto")
        text = self.cli("cli", "param-dump", "--format=var_export").stdout
        self.assertTrue(text.startswith("{'admin-email': {"))
        self.assertIn(pprint.pformat("--url=<url>"), text)

    def test_has_command(self):
        for args in (["site"], ["site", "create"], ["site create"], ["cli", "has-command"],
                     ["cfg", "get"]):
            result = self.cli("cli", "has-command", *args)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""), args)
        for args in (["sitee"], ["site", "nope"], ["site create extra"], [""]):
            result = self.cli("cli", "has-command", *args)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (1, "", ""), args)

    def test_aliases(self):
        write(os.path.join(self.root, "config", "config.yml"), textwrap.dedent("""\
            locale: en_US
            installer_version: stable
            "@prod":
              ssh: deploy@prod.example.com/var/www
            "@dev":
              path: /srv/dev
        """))
        result = self.cli("cli", "alias")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = yaml.safe_load(result.stdout)
        self.assertEqual(list(data), ["@all", "@dev", "@prod"])
        self.assertEqual(data["@prod"], {"ssh": "deploy@prod.example.com/var/www"})
        self.assertEqual(json.loads(self.cli("cli", "alias", "--format=json").stdout), data)
        self.assertEqual(self.cli("cli", "aliases").stdout, result.stdout)
        self.assertEqual(self.cli("cli", "aliases", "--format=json").stdout,
                         self.cli("cli", "alias", "--format=json").stdout)


class CompletionTest(Case):
    def setUp(self):
        super().setUp()
        self.init()

    def complete(self, line, point=None, shell=None, **env):
        args = ["cli", "completions", f"--line={line}",
                f"--point={len(line) if point is None else point}"]
        if shell:
            args.append(f"--shell={shell}")
        result = self.cli(*args, **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def test_root_includes_aliases_sorted(self):
        write(os.path.join(self.root, "config", "config.yml"), '"@prod":\n  ssh: h\n')
        found = self.complete("appctl ")
        self.assertEqual(found, sorted(found, key=lambda s: (s.lower(), s)))
        self.assertIn("@prod ", found)
        self.assertIn("@all ", found)
        self.assertIn("site ", found)
        self.assertEqual(self.complete("appctl @p"), ["@prod "])
        self.assertIn("list ", self.complete("appctl @prod site "))

    def test_subcommands_and_flags(self):
        self.assertEqual(self.complete("appctl site cr"), ["create "])
        flags = self.complete("appctl site create foo --")
        self.assertEqual(flags, sorted(flags))
        self.assertIn("--type=", flags)
        self.assertIn("--porcelain ", flags)
        self.assertIn("--url=", flags)
        self.assertNotIn("--type=", self.complete("appctl site create foo --type=x --"))

    def test_point(self):
        self.assertEqual(self.complete("appctl si create", point=9), ["site "])

    def test_file_marker(self):
        self.assertEqual(self.complete("appctl db import "), ["<file> "])
        self.assertIn("--porcelain ", self.complete("appctl db export --"))

    def test_zsh_descriptions(self):
        found = self.complete("appctl site cr", shell="zsh")
        self.assertEqual(found, ["create:Creates a site."])
        for line in self.complete("appctl ", shell="zsh"):
            self.assertRegex(line, r"^[^ :]+:\S")
        self.assertEqual(self.cli("cli", "completions", "--line=x", "--point=1",
                                  "--shell=fish").returncode, 1)

    def test_not_logged(self):
        log = os.path.join(self.root, "logs", "appctl.log")
        before = read(log)
        self.complete("appctl site ")
        self.assertEqual(read(log), before)


# -- updates --------------------------------------------------------------------------------------


class UpdateCase(Case):
    def releases(self, *versions, url=None, extra=()):
        data = [{"tag_name": f"v{v}",
                 "assets": [{"browser_download_url": url or f"https://example.test/{v}.pyz"}]}
                for v in versions]
        data += list(extra)
        path = write(os.path.join(self.tmp, "releases.json"), json.dumps(data))
        self.env["APPCTL_RELEASES_URL"] = "file://" + path


class CheckUpdateTest(UpdateCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.releases("1.0.1", "1.0.3", "1.2.0", "1.1.5", "2.0.0", "3.1.0", "0.9.0", "1.0.0",
                      extra=[{"tag_name": "v9.0.0", "prerelease": True, "assets": []},
                             {"tag_name": "v8.0.0", "draft": True, "assets": []}])

    def check(self, *args):
        result = self.cli("cli", "check-update", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_all_types(self):
        rows = json.loads(self.check("--format=json"))
        self.assertEqual([(r["version"], r["update_type"]) for r in rows],
                         [("3.1.0", "major"), ("1.2.0", "minor"), ("1.0.3", "patch")])
        self.assertEqual(list(rows[0]), ["version", "update_type", "package_url"])
        self.assertEqual(rows[0]["package_url"], "https://example.test/3.1.0.pyz")
        self.assertEqual(self.check("--format=count"), "3\n")
        self.assertEqual(self.check("--field=version"), "3.1.0\n1.2.0\n1.0.3\n")
        self.assertEqual(yaml.safe_load(self.check("--format=yaml")), rows)
        self.assertEqual(self.check("--format=csv").splitlines()[0],
                         "version,update_type,package_url")
        self.assertIn("| version | update_type | package_url", self.check())

    def test_filters_last_wins(self):
        def versions(*args):
            return [r["version"] for r in json.loads(self.check("--format=json", *args))]
        self.assertEqual(versions("--patch"), ["1.0.3"])
        self.assertEqual(versions("--minor"), ["1.2.0"])
        self.assertEqual(versions("--major"), ["3.1.0"])
        self.assertEqual(versions("--patch", "--major"), ["3.1.0"])
        self.assertEqual(versions("--major", "--patch"), ["1.0.3"])
        self.assertEqual(versions("--patch", "--major", "--patch"), ["1.0.3"])
        # single result stays a horizontal table
        self.assertIn("| 1.2.0   | minor", self.check("--minor"))

    def test_up_to_date(self):
        self.releases("1.0.0", "0.5.0")
        self.assertEqual(self.check(), "Success: AppCtl is up to date: it is at the latest version.\n")
        self.assertEqual(self.check("--format=table", "--minor"),
                         "Success: AppCtl is up to date: it is at the latest minor version.\n")
        self.assertEqual(self.check("--format=json"), "[]\n")
        self.assertEqual(self.check("--format=count"), "0\n")
        self.releases("1.0.1")
        self.assertIn("latest major version", self.check("--major"))

    def test_errors(self):
        self.assertEqual(self.cli("cli", "check-update", "--format=ids").returncode, 1)
        result = self.cli("cli", "check-update",
                          APPCTL_RELEASES_URL="file://" + os.path.join(self.tmp, "missing.json"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Failed to get the latest version", result.stderr)

    def test_update_types(self):
        self.assertEqual(self_update.update_type("1.0.1", "1.0.0"), "patch")
        self.assertEqual(self_update.update_type("1.10.0", "1.9.9"), "minor")
        self.assertEqual(self_update.update_type("2.0.0", "1.9.9"), "major")
        self.assertIsNone(self_update.update_type("1.0.0", "1.0.0"))
        self.assertIsNone(self_update.update_type("1.0.0", "1.0.1"))

    def test_nightly_source(self):
        version_file = write(os.path.join(self.tmp, "NIGHTLY_VERSION"), "1.0.1-nightly.20261111\n")
        env = {"APPCTL_NIGHTLY_VERSION_URL": "file://" + version_file,
               "APPCTL_NIGHTLY_URL": "https://example.test/nightly.pyz"}
        with mock.patch.object(self_update, "stable_releases") as stable:
            updates = self_update.available_updates(env, "1.0.1-nightly.20261101")
            stable.assert_not_called()
        self.assertEqual(updates, [{"version": "1.0.1-nightly.20261111", "update_type": "nightly",
                                    "package_url": "https://example.test/nightly.pyz",
                                    "status": "available"}])
        self.assertEqual(self_update.available_updates(env, "1.0.1-nightly.20261111"), [])


class SelfUpdateTest(UpdateCase):
    def setUp(self):
        super().setUp()
        self.target = write(os.path.join(self.tmp, "install", "appctl"), "old binary\n", 0o755)

    def new_binary(self, version="1.1.0", name="new.pyz"):
        return write(os.path.join(self.tmp, "dl", name),
                     f"import sys\nprint({version!r} if sys.argv[1:] == ['cli', 'version'] "
                     f"else 'unexpected')\n")

    def update(self, assoc=None, argv=(), platform_name="Linux", stdin=""):
        output = self.output()
        output._stdin = io.StringIO(stdin)
        assoc = {"yes": True} if assoc is None else assoc
        return self_update.self_update(self.env, output, assoc, argv,
                                       current="1.0.0", platform_name=platform_name,
                                       target=self.target)

    def test_darwin_refused(self):
        with self.assertRaises(AppctlError) as ctx:
            self.update(platform_name="Darwin")
        self.assertEqual(ctx.exception.message, "Self-update is not available. "
                                                "Please use your system package manager to update.")
        self.assertEqual(read(self.target), "old binary\n")

    def test_success(self):
        new = self.new_binary()
        self.releases("1.1.0", "1.0.1", url="file://" + new)
        self.assertEqual(self.update(), 0)
        self.assertEqual(read(self.target), read(new))
        self.assertTrue(os.access(self.target, os.X_OK))
        self.assertTrue(self.out.getvalue().endswith("Success: Updated AppCtl to 1.1.0.\n"))
        self.assertEqual(os.listdir(os.path.dirname(self.target)), ["appctl"])

    def test_filter(self):
        new = self.new_binary("1.0.1")
        self.releases("1.1.0", "1.0.1", url="file://" + new)
        self.update({"yes": True, "patch": True}, ["--patch"])
        self.assertIn("Updated AppCtl to 1.0.1.", self.out.getvalue())

    def test_confirmation(self):
        self.releases("1.1.0", url="file://" + self.new_binary())
        self.assertEqual(self.update({}, stdin="n\n"), 0)
        self.assertEqual(read(self.target), "old binary\n")
        self.assertIn("Would you like to update to 1.1.0? [y/n]", self.out.getvalue())
        self.update({}, stdin="y\n")
        self.assertIn("Updated AppCtl to 1.1.0.", self.out.getvalue())

    def test_validation_failure_keeps_old_binary(self):
        broken = write(os.path.join(self.tmp, "dl", "broken.pyz"), "raise SystemExit(3)\n")
        garbage = write(os.path.join(self.tmp, "dl", "garbage.pyz"), "\x00\x01 not python")
        for path in (broken, garbage):
            self.releases("1.1.0", url="file://" + path)
            with self.assertRaises(AppctlError) as ctx:
                self.update()
            self.assertIn("broken", ctx.exception.message)
            self.assertEqual(read(self.target), "old binary\n")
            self.assertEqual(os.listdir(os.path.dirname(self.target)), ["appctl"])

    def test_checksum_mismatch(self):
        new = self.new_binary()
        write(new + ".sha256", "0" * 64 + "  new.pyz\n")
        self.releases("1.1.0", url="file://" + new)
        with self.assertRaises(AppctlError) as ctx:
            self.update()
        self.assertIn("sha256 hash", ctx.exception.message)
        self.assertEqual(read(self.target), "old binary\n")

    def test_already_latest(self):
        self.releases("1.0.0")
        self.assertEqual(self.update(), 0)
        self.assertIn("up to date", self.out.getvalue())

    def test_stable_and_nightly(self):
        stable = self.new_binary("1.1.0", "stable.pyz")
        self.releases("1.1.0", "0.9.0", url="file://" + stable)
        self.update({"yes": True, "stable": True}, ["--stable"])
        self.assertIn("Updated AppCtl to 1.1.0.", self.out.getvalue())
        nightly = self.new_binary("1.2.0-nightly.1", "nightly.pyz")
        self.env["APPCTL_NIGHTLY_URL"] = "file://" + nightly
        self.env["APPCTL_NIGHTLY_VERSION_URL"] = "file://" + os.path.join(self.tmp, "missing")
        self.update({"yes": True, "nightly": True}, ["--nightly"])
        self.assertIn("Updated AppCtl to 1.2.0-nightly.1.", self.out.getvalue())
        self.assertEqual(read(self.target), read(nightly))

    def test_archive_end_to_end(self):
        archive = build(os.path.join(self.tmp, "install", "appctl.pyz"))
        source = os.path.join(self.tmp, "src")
        shutil.copytree(os.path.join(ROOT, "appctl_cli"), os.path.join(source, "appctl_cli"))
        init = os.path.join(source, "appctl_cli", "__init__.py")
        write(init, read(init).replace(f'"{__version__}"', '"1.5.0"'))
        sys.path.insert(0, source)
        try:
            import importlib
            builder = importlib.import_module("build_archive")
            builder.ROOT = source
            new = builder.build(os.path.join(self.tmp, "dl", "appctl-1.5.0.pyz"))
            builder.ROOT = ROOT
        finally:
            sys.path.remove(source)
        self.releases("1.5.0", url="file://" + new)
        result = self.cli("cli", "update", "--yes", script=archive)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Success: Updated AppCtl to 1.5.0.", result.stdout)
        result = self.cli("cli", "version", script=archive)
        self.assertEqual(result.stdout, "1.5.0\n")


class ArchiveModeTest(Case):
    def test_info_and_paths(self):
        archive = build(os.path.join(self.tmp, "dist", "appctl.pyz"))
        result = self.cli("cli", "info", "--format=json", script=archive)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["appctl_archive_path"], archive)
        self.assertEqual(data["appctl_binary_path"], os.path.realpath(archive))
        source = json.loads(self.cli("cli", "info", "--format=json").stdout)
        self.assertIsNone(source["appctl_archive_path"])


# -- self-uninstall ------------------------------------------------------------------------------


class SelfUninstallTest(Case):
    def setUp(self):
        super().setUp()
        self.init()
        self.project = os.path.join(self.tmp, "sites", "blog")
        write(os.path.join(self.project, "docker-compose.yml"), "services: {}\n")
        db = database.get_db(self.env)
        db.add_project("blog", self.project)
        database.close_all()
        self.env.update(FAKE_IDS_CONTAINERS="c1\nc2\n", FAKE_IDS_NETWORKS="n1\n",
                        FAKE_IDS_VOLUMES="v1\nv2\n", FAKE_IDS_IMAGES="i1\ni1\n")

    def test_removes_everything(self):
        result = self.cli("cli", "self-uninstall", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Success: AppCtl has been removed successfully.", result.stdout)
        calls = self.docker_calls()
        self.assertIn("rm -f c1 c2", calls)
        self.assertIn("network rm n1", calls)
        self.assertIn("volume rm -f v1 v2", calls)
        self.assertIn("rmi -f i1", calls)
        label = f"label={container.VENDOR_LABEL}"
        self.assertIn(f"ps -aq --filter {label}", calls)
        self.assertFalse(os.path.exists(self.project))
        self.assertFalse(os.path.exists(self.root))

    def test_prompt(self):
        result = self.cli("cli", "self-uninstall", input="n\n")
        self.assertEqual(result.returncode, 0)
        self.assertIn("irreversible", result.stdout)
        self.assertTrue(os.path.isdir(self.root))
        self.assertTrue(os.path.isdir(self.project))
        self.assertFalse([c for c in self.docker_calls() if c.startswith(("rm", "network rm"))])
        result = self.cli("cli", "self-uninstall", input="y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(os.path.exists(self.root))

    def test_requirements_checked_first(self):
        result = self.cli("cli", "self-uninstall", "--yes", FAKE_PS_FAIL="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Error: Container runtime is either not installed or not running.",
                      result.stderr)
        self.assertTrue(os.path.isdir(self.root))
        self.assertTrue(os.path.isdir(self.project))
        self.assertNotIn("irreversible", result.stdout)

    def test_removes_archive(self):
        archive = build(os.path.join(self.tmp, "dist", "appctl.pyz"))
        result = self.cli("cli", "self-uninstall", "--yes", script=archive)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(os.path.exists(archive))
        self.assertFalse(os.path.exists(self.root))


if __name__ == "__main__":
    unittest.main()
