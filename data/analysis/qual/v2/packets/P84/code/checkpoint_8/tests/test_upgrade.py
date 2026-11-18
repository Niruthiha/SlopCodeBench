"""Upgrade orchestration: migrations, image pulls, container upgrades and rollback."""

import io
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from collections import namedtuple
from unittest import mock

from appctl_cli import __version__, container, database, upgrade
from appctl_cli.errors import AppctlError
from appctl_cli.output import Output
from appctl_cli.revertable import RevertableStepProcessor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "appctl.py")

FAKE_DOCKER = textwrap.dedent("""\
    #!/bin/sh
    echo "$*" >> "$FAKE_DOCKER_LOG"
    if [ -n "$FAKE_DOCKER_FAIL" ]; then
      case "$*" in $FAKE_DOCKER_FAIL) exit 1 ;; esac
    fi
    case "$*" in
      "compose version"*)
        [ -n "$FAKE_NO_COMPOSE_PLUGIN" ] && exit 1
        echo "${FAKE_COMPOSE_VERSION:-2.29.7}"; exit 0 ;;
      "info"*) echo "$FAKE_DOCKER_ROOT"; exit 0 ;;
      "images"*) printf "%s" "$FAKE_IMAGES"; exit 0 ;;
    esac
    exit 0
""")

MIGRATION = textwrap.dedent("""\
    import os

    def _log(ctx, text):
        with open(ctx.environ["MIG_LOG"], "a") as handle:
            handle.write(text + "\\n")

    def up(ctx):
        _log(ctx, "up " + ctx.source + " " + ctx.name)
        if ctx.name in ctx.environ.get("MIG_FAIL", "").split(","):
            raise RuntimeError("boom")

    def down(ctx):
        _log(ctx, "down " + ctx.source + " " + ctx.name)
        if ctx.name in ctx.environ.get("MIG_DOWN_FAIL", "").split(","):
            raise RuntimeError("down boom")
""")

TARGETS = {"appctl/nginx-proxy": "v2", "appctl/php": "v2", "appctl/redis": "v1"}
Usage = namedtuple("Usage", "total used free")


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    if mode:
        os.chmod(path, mode)


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class UpgradeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.bin = os.path.join(self.tmp, "bin")
        write(os.path.join(self.bin, "docker"), FAKE_DOCKER, 0o755)
        self.root = os.path.join(self.tmp, "home")
        self.packages = os.path.join(self.tmp, "packages")
        self.log = os.path.join(self.tmp, "docker.log")
        self.mig_log = os.path.join(self.tmp, "mig.log")
        self.env = {
            "PATH": self.bin + os.pathsep + "/bin:/usr/bin",
            "HOME": self.tmp,
            "FAKE_DOCKER_LOG": self.log,
            "FAKE_DOCKER_ROOT": os.path.join(self.tmp, "docker-root"),
            "APPCTL_ROOT_DIR": self.root,
            "APPCTL_PACKAGES_DIR": self.packages,
            "MIG_LOG": self.mig_log,
        }
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(upgrade, "CORE_MIGRATIONS_DIR",
                                    os.path.join(self.tmp, "core", "migrations"))
        patcher.start()
        self.addCleanup(patcher.stop)
        container._compose_binary.clear()
        self.addCleanup(container._compose_binary.clear)
        self.addCleanup(database.close_all)
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.output = Output(stdout=self.stdout, stderr=self.stderr)
        self.db = database.get_db(os.environ)

    def migration(self, source, type, filename):
        base = (os.path.join(self.tmp, "core") if source == "appctl"
                else os.path.join(self.packages, *source.split("/")))
        path = os.path.join(base, "migrations", type, filename)
        write(path, MIGRATION)
        return path

    def calls(self):
        if not os.path.exists(self.log):
            return []
        return [line.rstrip("\n") for line in read(self.log).splitlines()
                if not line.startswith("compose version")]

    def mig_calls(self):
        return read(self.mig_log).splitlines() if os.path.exists(self.mig_log) else []

    def run_upgrade(self, targets=TARGETS):
        return upgrade.Upgrade(os.environ, self.output, self.db, dict(targets)).run()

    def compose_project(self, directory, services):
        lines = ["services:"] + [f"  {name}:\n    image: {image}" for name, image in services]
        path = os.path.join(directory, "docker-compose.yml")
        write(path, "\n".join(lines) + "\n")
        return path


class RevertableTest(unittest.TestCase):
    def test_rollback_reverse_and_continue(self):
        events = []
        stderr = io.StringIO()
        processor = RevertableStepProcessor(Output(stderr=stderr, stdout=io.StringIO()))

        def fail():
            raise RuntimeError("nope")

        def bad_undo():
            events.append("undo b")
            raise RuntimeError("undo failed")

        processor.add_step("a", lambda: events.append("a"), lambda: events.append("undo a"))
        processor.add_step("b", lambda: events.append("b"), bad_undo)
        processor.add_step("c", lambda: events.append("c"))
        processor.add_step("d", fail, lambda: events.append("undo d"))
        processor.add_step("e", lambda: events.append("e"), lambda: events.append("undo e"))
        self.assertFalse(processor.execute())
        self.assertEqual(events, ["a", "b", "c", "undo d", "undo b", "undo a"])
        self.assertIn("Unable to roll back step 'b': undo failed", stderr.getvalue())
        self.assertEqual(str(processor.error), "nope")

    def test_false_return_fails(self):
        processor = RevertableStepProcessor()
        processor.add_step("x", lambda: False)
        self.assertFalse(processor.execute())


class SemverTest(unittest.TestCase):
    def test_compare(self):
        self.assertEqual(upgrade.compare_semver("1.29.2", "2.27.0"), -1)
        self.assertEqual(upgrade.compare_semver("v2.27.0", "2.27"), 0)
        self.assertEqual(upgrade.compare_semver("2.100.0", "2.27.0"), 1)
        self.assertEqual(upgrade.compare_semver("2.27.0-rc.1", "2.27.0"), -1)
        self.assertEqual(upgrade.compare_semver("2.27.0-rc.2", "2.27.0-rc.10"), -1)


class MigrationTest(UpgradeCase):
    def test_discovery_order_and_sources(self):
        self.migration("appctl", "db", "20240102000000_b.py")
        self.migration("ext", "db", "20240101000000_a.py")
        self.migration("vendor/tool", "db", "20240102000000_b.py")
        self.migration("ext", "container", "20240101000000_c.py")
        write(os.path.join(self.packages, "ext", "migrations", "db", "notes.txt"), "")
        found = upgrade.discover_migrations("db")
        self.assertEqual([a.identity for a in found],
                         ["ext:20240101000000_a", "appctl:20240102000000_b",
                          "vendor/tool:20240102000000_b"])
        self.db.record_migration("ext:20240101000000_a", "db")
        self.assertEqual([a.identity for a in upgrade.pending_migrations(self.db, "db")],
                         ["appctl:20240102000000_b", "vendor/tool:20240102000000_b"])

    def test_success_records(self):
        self.migration("appctl", "db", "2_second.py")
        self.migration("ext", "db", "1_first.py")
        self.migration("ext", "container", "1_first.py")
        self.run_upgrade({})
        self.assertEqual(self.mig_calls(), ["up ext 1_first", "up appctl 2_second",
                                            "up ext 1_first"])
        records = self.db.get_migrations()
        self.assertEqual([(r["migration"], r["type"]) for r in records],
                         [("appctl:2_second", "db"), ("ext:1_first", "container"),
                          ("ext:1_first", "db")])
        self.assertTrue(all(r["timestamp"].endswith("Z") for r in records))
        self.assertEqual(self.db.get_option("version"), __version__)
        # nothing pending: silent
        self.stdout.truncate(0)
        self.run_upgrade({})
        self.assertEqual(len(self.mig_calls()), 3)
        self.assertEqual(self.stderr.getvalue(), "")

    def test_failure_rolls_back_batch(self):
        for name in ("1_a.py", "2_b.py", "3_c.py", "4_d.py"):
            self.migration("ext", "db", name)
        os.environ["MIG_FAIL"] = "3_c"
        os.environ["MIG_DOWN_FAIL"] = "2_b"
        with self.assertRaises(AppctlError) as ctx:
            self.run_upgrade({})
        self.assertEqual(ctx.exception.message, upgrade.MIGRATION_ERROR)
        self.assertEqual(self.mig_calls(), ["up ext 1_a", "up ext 2_b", "up ext 3_c",
                                            "down ext 2_b", "down ext 1_a"])
        self.assertEqual(self.db.get_migrations(), [])
        self.assertIn("Error: Migration 'ext:3_c' failed: boom", self.stderr.getvalue())
        self.assertIn("Unable to roll back step 'ext:2_b'", self.stderr.getvalue())
        self.assertFalse(self.db.get_option("version"))

    def test_container_failure_rolls_back_db_batch(self):
        self.migration("ext", "db", "1_a.py")
        self.migration("ext", "container", "1_b.py")
        os.environ["MIG_FAIL"] = "1_b"
        with self.assertRaises(AppctlError):
            self.run_upgrade({})
        self.assertEqual(self.mig_calls(), ["up ext 1_a", "up ext 1_b", "down ext 1_a"])
        self.assertEqual(self.db.get_migrations(), [])

    def test_missing_file(self):
        path = self.migration("ext", "db", "1_a.py")
        real = upgrade.discover_migrations

        def discover(type, environ=None):
            found = real(type, environ)
            os.unlink(path)
            return found

        with mock.patch.object(upgrade, "discover_migrations", discover):
            with self.assertRaises(AppctlError):
                self.run_upgrade({})
        self.assertIn(f"Error: Migration file not found: {path}", self.stderr.getvalue())


class ImageTest(UpgradeCase):
    def test_pull_changed_sequentially_and_finalize(self):
        self.db.set_option("appctl/redis", "v1")
        # php: observed v1 locally; nginx-proxy: target already present; nginx: absent
        os.environ["FAKE_IMAGES"] = ("appctl/php:v1\nappctl/nginx-proxy:v0\n"
                                     "appctl/nginx-proxy:v2\n")
        targets = dict(TARGETS, **{"appctl/nginx": "v2"})
        self.run_upgrade(targets)
        calls = self.calls()
        self.assertEqual([c for c in calls if c.startswith("pull")],
                         ["pull appctl/nginx:v2", "pull appctl/php:v2"])
        self.assertEqual({k: self.db.get_option(k) for k in targets}, targets)
        self.assertIn("rmi appctl/nginx-proxy:v0", calls)
        self.assertIn("rmi appctl/php:v1", calls)
        self.assertIn(f"network prune -f --filter label={container.VENDOR_LABEL}", calls)
        self.assertIn(f"image prune -f --filter label={container.VENDOR_LABEL}", calls)

    def test_pull_failure(self):
        self.migration("ext", "db", "1_a.py")
        os.environ["FAKE_DOCKER_FAIL"] = "pull appctl/php*"
        with self.assertRaises(AppctlError):
            self.run_upgrade()
        self.assertIn("Error: Unable to pull appctl/php:v2. Please check logs for more details.",
                      self.stderr.getvalue())
        self.assertNotIn("pull appctl/redis:v1", self.calls())
        self.assertEqual(self.mig_calls(), ["up ext 1_a", "down ext 1_a"])
        self.assertFalse(self.db.get_option("version"))

    def test_prune_failure_not_fatal(self):
        os.environ["FAKE_DOCKER_FAIL"] = "network prune*"
        self.assertTrue(self.run_upgrade())
        self.assertIn("Warning: Unable to prune old networks.", self.stderr.getvalue())
        self.assertEqual(self.db.get_option("version"), __version__)


class ContainerUpgradeTest(UpgradeCase):
    def setUp(self):
        super().setUp()
        for image, tag in TARGETS.items():
            self.db.set_option(image, "v1")
        self.global_dir = os.path.join(self.root, "services")
        self.global_file = self.compose_project(self.global_dir, [
            ("proxy", "appctl/nginx-proxy:v1"), ("redis", "appctl/redis:v1")])
        self.site_a = os.path.join(self.tmp, "sites", "a")
        self.site_b = os.path.join(self.tmp, "sites", "b")
        self.file_a = self.compose_project(self.site_a, [("php", "appctl/php:v1"),
                                                         ("cache", "appctl/redis:v1")])
        self.file_b = self.compose_project(self.site_b, [("cache", "appctl/redis:v1")])
        self.db.add_project("a", self.site_a)
        self.db.add_project("b", self.site_b)

    def ups(self):
        return [c.split(" -p ")[1] for c in self.calls() if " up -d" in c]

    def test_only_changed(self):
        self.run_upgrade()
        self.assertEqual(self.ups(), ["appctlglobal up -d --no-deps proxy",
                                      "a up -d --no-deps php"])
        self.assertIn("image: appctl/nginx-proxy:v2", read(self.global_file))
        self.assertIn("image: appctl/redis:v1", read(self.global_file))
        self.assertIn("image: appctl/php:v2", read(self.file_a))
        self.assertNotIn("stop", " ".join(self.calls()))

    def test_project_failure_restores_everything(self):
        self.migration("ext", "db", "1_a.py")
        os.environ["FAKE_DOCKER_FAIL"] = "*-p a up*"
        before = (read(self.global_file), read(self.file_a))
        with self.assertRaises(AppctlError) as ctx:
            self.run_upgrade()
        self.assertEqual(ctx.exception.message, upgrade.MIGRATION_ERROR)
        self.assertEqual((read(self.global_file), read(self.file_a)), before)
        # project a: failed up, revert up; global: up, then revert up with old images
        self.assertEqual(self.ups(), ["appctlglobal up -d --no-deps proxy",
                                      "a up -d --no-deps php", "a up -d --no-deps php",
                                      "appctlglobal up -d --no-deps proxy"])
        self.assertEqual(self.db.get_option("appctl/php"), "v1")
        self.assertEqual(self.db.get_migrations(), [])
        self.assertEqual(self.mig_calls(), ["up ext 1_a", "down ext 1_a"])

    def test_flow_style_rewrite(self):
        text = "services:\n  web: {image: 'appctl/php:v1', ports: [80]}\n  x: {image: other}\n"
        self.assertEqual(upgrade.rewrite_images(text, {"appctl/php": "v2"}),
                         "services:\n  web: {image: 'appctl/php:v2', ports: [80]}\n"
                         "  x: {image: other}\n")
        self.assertEqual(upgrade.split_image("host:5000/img"), ("host:5000/img", None))


class ComposeToolTest(UpgradeCase):
    def setUp(self):
        super().setUp()
        os.environ["FAKE_NO_COMPOSE_PLUGIN"] = "1"
        self.legacy = os.path.join(self.bin, "docker-compose")
        self.old = "#!/bin/sh\necho 1.29.2\n"
        write(self.legacy, self.old, 0o755)
        self.download = os.path.join(self.tmp, "download", "docker-compose")
        os.environ[upgrade.COMPOSE_URL_ENV] = "file://" + self.download

    def test_upgrade(self):
        write(self.download, "#!/bin/sh\necho 2.29.7\n")
        self.run_upgrade({})
        self.assertIn("2.29.7", read(self.legacy))
        self.assertTrue(os.stat(self.legacy).st_mode & stat.S_IXUSR)
        self.assertFalse(os.path.exists(self.legacy + ".backup"))

    def test_failed_upgrade_keeps_old(self):
        write(self.download, "#!/bin/sh\necho 1.0.0\n")
        self.run_upgrade({})
        self.assertEqual(read(self.legacy), self.old)
        self.assertIn("Unable to upgrade the compose tool", self.stderr.getvalue())
        self.assertFalse(os.path.exists(self.legacy + ".new"))

    def test_later_failure_restores_old(self):
        write(self.download, "#!/bin/sh\necho 2.29.7\n")
        self.migration("ext", "container", "1_a.py")
        with mock.patch.object(upgrade.Upgrade, "_save_state", side_effect=RuntimeError("x")):
            with self.assertRaises(AppctlError):
                self.run_upgrade({})
        self.assertEqual(read(self.legacy), self.old)

    def test_current_version_untouched(self):
        write(self.legacy, "#!/bin/sh\necho 2.27.0\n", 0o755)
        self.run_upgrade({})
        self.assertIn("2.27.0", read(self.legacy))


class DiskSpaceTest(UpgradeCase):
    def test_insufficient(self):
        self.migration("ext", "db", "1_a.py")
        runtime_root = os.path.join(self.tmp, "docker-root")

        def usage(path):
            low = path.startswith(runtime_root) or runtime_root.startswith(path + os.sep)
            return Usage(10, 10, 1024 if low else 10 * 1024 ** 3)

        with mock.patch.object(upgrade.shutil, "disk_usage", usage):
            with self.assertRaises(AppctlError) as ctx:
                self.run_upgrade()
        self.assertIn("minimum 5GB disk space is required", ctx.exception.message)
        self.assertEqual(self.mig_calls(), [])
        self.assertEqual([c for c in self.calls() if not c.startswith("info")], [])


class CliTest(UpgradeCase):
    def cli(self, *args):
        database.close_all()
        result = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                                env=dict(os.environ), cwd=self.tmp)
        self.db = database.get_db(os.environ)
        return result

    def test_migrate_failure_exit_code(self):
        self.migration("ext", "db", "1_a.py")
        self.migration("ext", "db", "2_b.py")
        os.environ["MIG_FAIL"] = "2_b"
        result = self.cli("cli", "migrate")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.endswith(
            "Error: There was some error while migrating. Please check logs.\n"))
        self.assertEqual(self.mig_calls(), ["up ext 1_a", "up ext 2_b", "down ext 1_a"])
        count = sqlite3.connect(database.db_path(os.environ)).execute(
            "SELECT COUNT(*) FROM migrations").fetchone()[0]
        self.assertEqual(count, 0)

    def test_automatic_on_version_change(self):
        self.migration("ext", "db", "1_a.py")
        self.assertEqual(self.cli("cli", "version").returncode, 0)
        self.assertEqual(self.mig_calls(), ["up ext 1_a"])  # first run: pending migrations
        self.migration("ext", "db", "2_b.py")
        self.db.set_option("version", "0.0.1")
        result = self.cli("cli", "version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"{__version__}\n")
        self.assertEqual(self.mig_calls(), ["up ext 1_a", "up ext 2_b"])
        self.assertEqual(self.db.get_option("version"), __version__)
        self.cli("cli", "version")
        self.assertEqual(self.mig_calls(), ["up ext 1_a", "up ext 2_b"])


if __name__ == "__main__":
    unittest.main()
