import io
import os
import sqlite3
import stat

import pytest

from appctl_core import catalog, compose_tool, db, migrations, semver, upgrade
from appctl_core.app import run
from appctl_core.containers import split_image
from appctl_core.errors import CliError
from appctl_core.output import Output
from appctl_core.revertable import RevertableStepProcessor

GIB = 1024 ** 3
OVERALL = "Error: There was some error while migrating. Please check logs.\n"

# A fake container runtime: logs every call, fails calls containing a line of
# $FAKE_STATE/fail and answers image and compose queries from state files.
FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$FAKE_LOG"
if [ -f "$FAKE_STATE/fail" ]; then
  while IFS= read -r pattern; do
    [ -n "$pattern" ] || continue
    case "$*" in *"$pattern"*) echo "failed: $*" >&2; exit 1 ;; esac
  done < "$FAKE_STATE/fail"
fi
case "$1 $2" in
  "info --format") echo "$FAKE_STATE/docker-root"; exit 0 ;;
  "image ls") [ -f "$FAKE_STATE/images" ] && cat "$FAKE_STATE/images"; exit 0 ;;
  "compose version")
    plugin="$HOME/.docker/cli-plugins/docker-compose"
    [ -x "$plugin" ] && exec "$plugin" version --short
    cat "$FAKE_STATE/compose-version" 2>/dev/null || echo 2.30.0
    exit 0 ;;
esac
exit 0
"""


class Fake:
    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        script = bin_dir / "docker"
        script.write_text(FAKE_DOCKER)
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        self.state = tmp_path / "state"
        self.state.mkdir()
        self.log = tmp_path / "docker.log"
        self.journal = tmp_path / "journal"
        self.root = tmp_path / "root"
        self.packages = tmp_path / "packages"
        self.tool = tmp_path / "tool"
        self.versions = tmp_path / "versions.json"
        self.versions.write_text("{}")
        (tmp_path / "home").mkdir()
        self.env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "FAKE_LOG": str(self.log),
                    "FAKE_STATE": str(self.state), "APPCTL_ROOT_DIR": str(self.root),
                    "APPCTL_PACKAGES_DIR": str(self.packages), "HOME": str(tmp_path / "home"),
                    "APPCTL_IMAGE_VERSIONS_FILE": str(self.versions),
                    "JOURNAL": str(self.journal)}
        self.free = {}
        monkeypatch.setattr(migrations, "TOOL_DIR", str(self.tool))
        monkeypatch.setattr(upgrade, "disk_free",
                            lambda path: self.free.get(str(path), 100 * GIB))

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def journal_lines(self):
        return self.journal.read_text().splitlines() if self.journal.exists() else []

    def fail(self, *patterns):
        (self.state / "fail").write_text("".join(p + "\n" for p in patterns))

    def call(self, *argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        code = run(list(argv), dict(self.env, **(env or {})), out, err, cwd=str(self.tmp),
                   stdin=io.StringIO(""))
        return code, out.getvalue(), err.getvalue()

    def store(self):
        return db.open_database(str(self.root))

    def migration(self, base, kind, name, up="", down="", fail=False):
        directory = base / "migrations" / kind
        directory.mkdir(parents=True, exist_ok=True)
        label = f"{base.name}/{name}"
        body = (
            "import os\n"
            "def _note(ctx, text):\n"
            "    with open(ctx.env['JOURNAL'], 'a') as handle:\n"
            "        handle.write(text + '\\n')\n"
            f"def up(ctx):\n    _note(ctx, 'up {label}')\n"
            + (f"    raise RuntimeError('boom {label}')\n" if fail else "")
            + f"def down(ctx):\n    _note(ctx, 'down {label}')\n")
        (directory / f"{name}.py").write_text(body)

    def migrations_recorded(self):
        with self.store() as store:
            return [(m["type"], m["migration"]) for m in store.get_migrations()]


@pytest.fixture
def fake(tmp_path, monkeypatch):
    return Fake(tmp_path, monkeypatch)


# --- revertable steps ------------------------------------------------------------

def output():
    out, err = io.StringIO(), io.StringIO()
    return Output(out, err), out, err


def test_steps_run_in_order_and_roll_back_in_reverse():
    log = []
    proc_out, _, err = output()
    processor = RevertableStepProcessor(proc_out)
    processor.add_step("a", lambda: log.append("up a"), lambda: log.append("down a"))
    processor.add_step("b", lambda: log.append("up b"))
    processor.add_step("c", lambda: log.append("up c"), lambda: 1 / 0)
    processor.add_step("d", lambda: log.append("up d"), lambda: log.append("down d"))
    processor.add_step("e", lambda: False, lambda: log.append("down e"))
    processor.add_step("f", lambda: log.append("up f"), lambda: log.append("down f"))
    assert processor.execute() is False
    assert processor.failed_step == "e"
    assert log == ["up a", "up b", "up c", "up d", "down e", "down d", "down a"]
    assert err.getvalue() == "Warning: Unable to revert step 'c': division by zero\n"


def test_successful_steps_can_be_rolled_back_once():
    log = []
    processor = RevertableStepProcessor(output()[0])
    processor.add_step("a", lambda x: log.append(x), lambda x: log.append("-" + x),
                       up_args=("a",), down_args=("a",))
    processor.add_step("b", lambda: log.append("b"), lambda: log.append("-b"))
    assert processor.execute() is True
    processor.rollback()
    processor.rollback()
    assert log == ["a", "b", "-b", "-a"]


# --- semver ------------------------------------------------------------------------

@pytest.mark.parametrize("low, high", [
    ("2.9.0", "2.10.0"), ("v1.29.2", "2.0.0"), ("2.20.2-rc.1", "2.20.2"),
    ("1.0.0-alpha", "1.0.0-alpha.1"), ("1.0.0-alpha.1", "1.0.0-alpha.beta"),
    ("1.0.0-beta.2", "1.0.0-beta.11"), ("2.20", "2.20.1"),
])
def test_semver_precedence(low, high):
    assert semver.is_lower(low, high) and not semver.is_lower(high, low)


def test_semver_equality_ignores_build_metadata():
    assert semver.compare("v2.20.2+abc", "2.20.2") == 0
    assert semver.parse("Docker Compose version v2.24.5-desktop.1").prerelease == (
        "desktop", "1")
    assert semver.parse("garbage") is None


# --- migration discovery -------------------------------------------------------------

def test_discovery_is_ordered_and_keeps_sources_distinct(fake):
    fake.migration(fake.tool, "db", "20240102000000_add_index")
    fake.migration(fake.packages / "zeta", "db", "20240102000000_add_index")
    fake.migration(fake.packages / "alpha", "db", "20240102000000_add_index")
    fake.migration(fake.packages / "vendor" / "pkg", "db", "20230101000000_first")
    fake.migration(fake.tool, "db", "9_short_prefix_sorts_numerically")
    fake.migration(fake.tool, "container", "20240101000000_container_only")
    (fake.tool / "migrations" / "db" / "notes.txt").write_text("ignored")
    (fake.tool / "migrations" / "db" / "__init__.py").write_text("")
    sources = migrations.default_sources(str(fake.packages))
    found = [m.identity for m in migrations.discover(sources, "db")]
    assert found == ["appctl:9_short_prefix_sorts_numerically",
                     "vendor/pkg:20230101000000_first",
                     "appctl:20240102000000_add_index",
                     "alpha:20240102000000_add_index",
                     "zeta:20240102000000_add_index"]
    assert [m.identity for m in migrations.discover(sources, "container")] == [
        "appctl:20240101000000_container_only"]
    with fake.store() as store:
        store.add_migration("alpha:20240102000000_add_index", "db")
        assert "alpha:20240102000000_add_index" not in [
            m.identity for m in migrations.pending(store, sources, "db")]
        assert "zeta:20240102000000_add_index" in [
            m.identity for m in migrations.pending(store, sources, "db")]


# --- migration execution -------------------------------------------------------------

def test_migrations_run_and_are_recorded(fake):
    fake.migration(fake.tool, "db", "2_second")
    fake.migration(fake.packages / "ext", "db", "1_first")
    fake.migration(fake.tool, "container", "1_container")
    code, out, err = fake.call("cli", "migrate")
    assert (code, err) == (0, ""), err
    assert out == "Success: Migrations and upgrades completed.\n"
    assert fake.journal_lines() == ["up ext/1_first", "up tool/2_second",
                                    "up tool/1_container"]
    assert fake.migrations_recorded() == [("container", "appctl:1_container"),
                                          ("db", "appctl:2_second"), ("db", "ext:1_first")]
    with fake.store() as store:
        assert all(m["timestamp"].endswith("Z") for m in store.get_migrations())
        assert store.get_option("version") == catalog.VERSION
    # Nothing is pending the second time.
    assert fake.call("cli", "migrate")[0] == 0
    assert len(fake.journal_lines()) == 3


def test_failed_migration_rolls_back_the_batch(fake):
    fake.migration(fake.tool, "db", "1_a")
    fake.migration(fake.tool, "db", "2_b")
    fake.migration(fake.tool, "db", "3_c", fail=True)
    fake.migration(fake.tool, "db", "4_d")
    with fake.store() as store:
        store.add_migration("appctl:0_old", "db")
    code, out, err = fake.call("cli", "migrate")
    assert (code, out) == (1, "")
    assert err == ("Error: Encountered error while running migration 'appctl:3_c': "
                   "boom tool/3_c\n" + OVERALL)
    assert fake.journal_lines() == ["up tool/1_a", "up tool/2_b", "up tool/3_c",
                                    "down tool/2_b", "down tool/1_a"]
    assert fake.migrations_recorded() == [("db", "appctl:0_old")]
    with fake.store() as store:
        assert store.get_option("version") is False


def test_failed_container_migration_rolls_back_everything(fake):
    fake.migration(fake.tool, "db", "1_a")
    fake.migration(fake.tool, "container", "1_x")
    fake.migration(fake.tool, "container", "2_y", fail=True)
    code, _, err = fake.call("cli", "migrate")
    assert code == 1 and err.endswith(OVERALL)
    assert fake.journal_lines() == ["up tool/1_a", "up tool/1_x", "up tool/2_y",
                                    "down tool/1_x", "down tool/1_a"]
    assert fake.migrations_recorded() == []
    assert not any(c.startswith("pull") for c in fake.calls())


def test_failing_down_is_logged_and_rollback_continues(fake):
    fake.migration(fake.tool, "db", "1_a")
    (fake.tool / "migrations" / "db" / "2_b.py").write_text(
        "def up():\n    pass\ndef down():\n    raise ValueError('cannot undo')\n")
    fake.migration(fake.tool, "db", "3_c", fail=True)
    code, _, err = fake.call("cli", "migrate")
    assert code == 1
    assert "Warning: Unable to roll back migration 'appctl:2_b': cannot undo\n" in err
    assert fake.journal_lines()[-1] == "down tool/1_a"
    assert fake.migrations_recorded() == []
    log = (fake.root / "logs" / "appctl.log").read_text()
    assert "Unable to roll back migration 'appctl:2_b': cannot undo" in log


def test_class_based_migration(fake):
    directory = fake.tool / "migrations" / "db"
    directory.mkdir(parents=True)
    (directory / "1_cls.py").write_text(
        "class Migration:\n"
        "    def up(self, ctx):\n"
        "        ctx.db.update_option('from-migration', ctx.identity)\n")
    assert fake.call("cli", "migrate")[0] == 0
    with fake.store() as store:
        assert store.get_option("from-migration") == "appctl:1_cls"


def test_missing_migration_file(fake, monkeypatch):
    fake.migration(fake.tool, "db", "1_a")
    gone = str(fake.tool / "migrations" / "db" / "2_gone.py")
    real_discover = migrations.discover

    def discover(sources, kind):
        found = real_discover(sources, kind)
        if kind == "db":
            found.append(migrations.Migration(sources[0], "db", gone))
        return found
    monkeypatch.setattr(migrations, "discover", discover)
    code, _, err = fake.call("cli", "migrate")
    assert code == 1
    assert f"Error: Unable to find migration file at '{gone}'.\n" in err
    assert fake.migrations_recorded() == []


def test_no_pending_migrations_is_silent(fake):
    code, out, err = fake.call("cli", "migrate")
    assert (code, err) == (0, "")


# --- automatic trigger ---------------------------------------------------------------

def test_first_run_runs_pending_migrations(fake):
    fake.migration(fake.tool, "db", "1_a")
    fake.migration(fake.tool, "container", "1_c")
    code, out, err = fake.call("help")
    assert (code, err) == (0, "")
    assert out.startswith("Success: AppCtl has been set up successfully.\n")
    assert fake.journal_lines() == ["up tool/1_a", "up tool/1_c"]
    with fake.store() as store:
        assert store.get_option("version") == catalog.VERSION
    # Not a first run any more.
    code, out, _ = fake.call("help")
    assert "Success" not in out and len(fake.journal_lines()) == 2


def test_first_run_keeps_machine_readable_output(fake):
    fake.migration(fake.tool, "db", "1_a")
    assert fake.call("cli", "version") == (0, f"{catalog.VERSION}\n", "")
    assert fake.journal_lines() == ["up tool/1_a"]


def test_failed_first_run_is_reported(fake):
    fake.migration(fake.tool, "db", "1_a")
    fake.migration(fake.tool, "db", "2_b", fail=True)
    code, out, err = fake.call("help")
    assert (code, out) == (1, "")
    assert err.endswith(OVERALL)
    assert fake.journal_lines() == ["up tool/1_a", "up tool/2_b", "down tool/1_a"]
    with fake.store() as store:
        assert store.get_option("version") is False


def test_version_change_runs_migrations_before_the_command(fake):
    fake.migration(fake.tool, "db", "1_a")
    with fake.store() as store:
        store.update_option("version", "0.9.0")
    assert fake.call("cli", "version") == (0, f"{catalog.VERSION}\n", "")
    assert fake.journal_lines() == ["up tool/1_a"]
    with fake.store() as store:
        assert store.get_option("version") == catalog.VERSION
    assert fake.call("cli", "version")[0] == 0
    assert fake.journal_lines() == ["up tool/1_a"]


def test_failed_automatic_upgrade_stops_the_command(fake):
    fake.migration(fake.tool, "db", "1_a", fail=True)
    with fake.store() as store:
        store.update_option("version", "0.9.0")
    code, out, err = fake.call("cli", "version")
    assert (code, out) == (1, "")
    assert err.endswith(OVERALL)
    with fake.store() as store:
        assert store.get_option("version") == "0.9.0"


# --- disk space ------------------------------------------------------------------------

@pytest.mark.parametrize("where", ["root", "runtime"])
def test_insufficient_disk_space_prevents_any_mutation(fake, where):
    fake.migration(fake.tool, "db", "1_a")
    fake.versions.write_text('{"appctl/nginx": "v2"}')
    path = str(fake.root) if where == "root" else str(fake.state / "docker-root")
    fake.free[path] = 5 * GIB - 1
    code, out, err = fake.call("cli", "migrate")
    assert (code, out) == (1, "")
    assert err.startswith("Error: Minimum 5GB disk space is required")
    assert err.count("Error:") == 1 and path in err
    assert fake.journal_lines() == [] and fake.migrations_recorded() == []
    assert fake.calls() == ["info --format {{.DockerRootDir}}"]


def test_exactly_five_gib_is_enough(fake):
    fake.free[str(fake.root)] = 5 * GIB
    assert fake.call("cli", "migrate")[0] == 0


# --- images ------------------------------------------------------------------------------

def test_changed_images_are_pulled_sequentially_and_recorded(fake):
    fake.versions.write_text('{"appctl/php": "v2", "appctl/nginx": "v3", "appctl/db": "v1"}')
    (fake.state / "images").write_text("appctl/nginx:v2\nappctl/db:v1\nappctl/db:v0\n")
    code, _, err = fake.call("cli", "migrate")
    assert code == 0, err
    pulls = [c for c in fake.calls() if c.startswith("pull")]
    assert pulls == ["pull appctl/nginx:v3", "pull appctl/php:v2"]
    with fake.store() as store:
        assert store.get_option("image:appctl/nginx") == "v3"
        assert store.get_option("image:appctl/php") == "v2"
        assert store.get_option("image:appctl/db") == "v1"
    calls = fake.calls()
    assert "image rm appctl/nginx:v2" in calls
    assert calls[-2:] == [
        "image prune --all --force --filter label=org.label-schema.vendor=AppCtl",
        "network prune --force --filter label=org.label-schema.vendor=AppCtl"]
    # Recorded versions are authoritative: nothing changes the next time.
    log_size = len(fake.calls())
    assert fake.call("cli", "migrate")[0] == 0
    assert not any(c.startswith("pull") for c in fake.calls()[log_size:])


def test_pull_failure_reports_and_rolls_back(fake):
    fake.migration(fake.tool, "db", "1_a")
    fake.versions.write_text('{"appctl/a": "v1", "appctl/b": "v1", "appctl/c": "v1"}')
    fake.fail("pull appctl/b")
    code, _, err = fake.call("cli", "migrate")
    assert code == 1
    assert err == ("Error: Unable to pull appctl/b:v1. Please check logs for more details.\n"
                   + OVERALL)
    assert [c for c in fake.calls() if c.startswith("pull")] == ["pull appctl/a:v1",
                                                                 "pull appctl/b:v1"]
    assert fake.migrations_recorded() == []
    with fake.store() as store:
        assert store.get_option("image:appctl/a") is False


def test_prune_failures_are_not_fatal(fake):
    fake.versions.write_text('{"appctl/a": "v1"}')
    fake.fail("prune")
    code, out, err = fake.call("cli", "migrate")
    assert code == 0 and err == ""
    with fake.store() as store:
        assert store.get_option("image:appctl/a") == "v1"


def test_rewrite_images_preserves_formatting():
    text = ("services:\n  web:\n    image: \"appctl/nginx:v1\"  # pinned\n"
            "  db:\n    image: mariadb:10\n  other:\n    image: appctl/nginx\r\n")
    assert upgrade.rewrite_images(text, {"appctl/nginx": "v2"}) == (
        "services:\n  web:\n    image: \"appctl/nginx:v2\"  # pinned\n"
        "  db:\n    image: mariadb:10\n  other:\n    image: appctl/nginx:v2\r\n")
    assert split_image("registry:5000/a/b:tag") == ("registry:5000/a/b", "tag")
    assert split_image("registry:5000/a/b") == ("registry:5000/a/b", None)


# --- global containers -----------------------------------------------------------------

GLOBAL = ("services:\n  proxy:\n    image: appctl/proxy:v1\n"
          "  db:\n    image: appctl/db:v1\n  cache:\n    image: appctl/cache:v1\n")


def write_global(fake):
    directory = fake.root / "services"
    directory.mkdir(parents=True)
    (directory / "docker-compose.yml").write_text(GLOBAL)
    with fake.store() as store:
        for image in ("proxy", "db", "cache"):
            store.update_option(f"image:appctl/{image}", "v1")
    fake.versions.write_text('{"appctl/proxy": "v2", "appctl/db": "v1", "appctl/cache": "v2"}')
    return directory


def compose_calls(fake, directory):
    prefix = f"compose -p {directory.name} -f {directory / 'docker-compose.yml'} "
    return [c[len(prefix):] for c in fake.calls() if c.startswith(prefix)]


def test_only_changed_global_containers_are_replaced(fake):
    directory = write_global(fake)
    code, _, err = fake.call("cli", "migrate")
    assert code == 0, err
    assert compose_calls(fake, directory) == ["stop proxy cache", "rm -f proxy cache",
                                              "up -d --no-deps proxy cache"]
    assert (directory / "docker-compose.yml").read_text() == GLOBAL.replace(
        "proxy:v1", "proxy:v2").replace("cache:v1", "cache:v2")


def test_failed_global_upgrade_restores_previous_state(fake):
    directory = write_global(fake)
    fake.migration(fake.tool, "db", "1_a")
    fake.fail("up -d --no-deps proxy cache")
    code, _, err = fake.call("cli", "migrate")
    assert code == 1
    assert "Error: Unable to start containers of 'global services': failed:" in err
    assert err.endswith(OVERALL)
    assert compose_calls(fake, directory) == [
        "stop proxy cache", "rm -f proxy cache", "up -d --no-deps proxy cache",
        "stop proxy cache", "rm -f proxy cache", "up -d --no-deps proxy cache"]
    assert (directory / "docker-compose.yml").read_text() == GLOBAL
    assert fake.migrations_recorded() == []
    with fake.store() as store:
        assert store.get_option("image:appctl/proxy") == "v1"
    assert not any("prune" in c for c in fake.calls())


# --- projects ----------------------------------------------------------------------------

def add_project(fake, name, image):
    directory = fake.tmp / "projects" / name
    directory.mkdir(parents=True)
    (directory / "docker-compose.yml").write_text(
        f"services:\n  app:\n    image: {image}\n  db:\n    image: mariadb:10\n")
    with fake.store() as store:
        store.add_project(name, str(directory))
    return directory


def test_only_projects_using_changed_images_are_upgraded(fake):
    fake.versions.write_text('{"appctl/php": "v2", "appctl/redis": "v1"}')
    with fake.store() as store:
        store.update_option("image:appctl/php", "v1")
        store.update_option("image:appctl/redis", "v1")
    changed = add_project(fake, "blog", "appctl/php:v1")
    same = add_project(fake, "shop", "appctl/redis:v1")
    code, _, err = fake.call("cli", "migrate")
    assert code == 0, err
    assert compose_calls(fake, changed) == ["stop", "rm -f", "up -d"]
    assert compose_calls(fake, same) == []
    assert "image: appctl/php:v2" in (changed / "docker-compose.yml").read_text()
    assert "image: appctl/redis:v1" in (same / "docker-compose.yml").read_text()


def test_failed_project_upgrade_restores_all_projects(fake):
    fake.versions.write_text('{"appctl/php": "v2"}')
    first = add_project(fake, "a", "appctl/php:v1")
    second = add_project(fake, "b", "appctl/php:v1")
    original = (second / "docker-compose.yml").read_text()
    fake.fail(f"-f {second / 'docker-compose.yml'} up -d")
    code, _, err = fake.call("cli", "migrate")
    assert code == 1 and err.endswith(OVERALL)
    assert compose_calls(fake, first) == ["stop", "rm -f", "up -d",
                                          "stop", "rm -f", "up -d"]
    assert compose_calls(fake, second) == ["stop", "rm -f", "up -d",
                                           "stop", "rm -f", "up -d"]
    assert (first / "docker-compose.yml").read_text() == original
    assert (second / "docker-compose.yml").read_text() == original


# --- compose tool ----------------------------------------------------------------------

def compose_binary(path, version):
    path.write_text(f"#!/bin/sh\necho {version}\n")
    path.chmod(0o755)


def test_outdated_compose_tool_is_upgraded(fake):
    (fake.state / "compose-version").write_text("2.10.0\n")
    source = fake.tmp / "compose-2.20.2"
    compose_binary(source, "v" + compose_tool.MIN_VERSION)
    env = {"APPCTL_COMPOSE_DOWNLOAD_URL": f"file://{fake.tmp}/compose-{{version}}"}
    code, _, err = fake.call("cli", "migrate", env=env)
    assert code == 0, err
    plugin = fake.tmp / "home" / ".docker" / "cli-plugins" / "docker-compose"
    assert plugin.read_text() == source.read_text()
    assert sorted(os.listdir(plugin.parent)) == ["docker-compose"]


def test_failed_compose_upgrade_keeps_previous_tool(fake):
    plugins = fake.tmp / "home" / ".docker" / "cli-plugins"
    plugins.mkdir(parents=True)
    compose_binary(plugins / "docker-compose", "2.0.0")
    previous = (plugins / "docker-compose").read_text()
    compose_binary(fake.tmp / "broken", "not-a-version")
    env = {"APPCTL_COMPOSE_DOWNLOAD_URL": f"file://{fake.tmp}/broken"}
    code, _, err = fake.call("cli", "migrate", env=env)
    assert code == 0
    assert err.startswith("Warning: Unable to upgrade the compose tool:")
    assert (plugins / "docker-compose").read_text() == previous
    assert sorted(os.listdir(plugins)) == ["docker-compose"]


def test_compose_upgrade_is_reverted_when_the_upgrade_fails(fake):
    plugins = fake.tmp / "home" / ".docker" / "cli-plugins"
    plugins.mkdir(parents=True)
    compose_binary(plugins / "docker-compose", "2.0.0")
    previous = (plugins / "docker-compose").read_text()
    compose_binary(fake.tmp / "good", "2.21.0")
    fake.versions.write_text('{"appctl/a": "v1"}')
    fake.fail("pull appctl/a")
    env = {"APPCTL_COMPOSE_DOWNLOAD_URL": f"file://{fake.tmp}/good"}
    assert fake.call("cli", "migrate", env=env)[0] == 1
    assert (plugins / "docker-compose").read_text() == previous
    assert sorted(os.listdir(plugins)) == ["docker-compose"]


def test_current_compose_tool_is_left_alone(fake):
    (fake.state / "compose-version").write_text("v2.20.2\n")
    assert fake.call("cli", "migrate")[0] == 0
    assert not (fake.tmp / "home" / ".docker").exists()


# --- database helpers ------------------------------------------------------------------

def test_projects_table(tmp_path):
    with db.open_database(str(tmp_path)) as store:
        store.add_project("b", "/srv/b")
        store.add_project("a", "/srv/a")
        store.add_project("b", "/srv/b2")
        assert [(p["name"], p["path"]) for p in store.get_projects()] == [
            ("a", "/srv/a"), ("b", "/srv/b2")]
        assert store.remove_project("a") and not store.remove_project("a")
        store.update_option("k", "v")
        assert store.delete_option("k") and store.get_option("k") is False
    tables = {r[0] for r in sqlite3.connect(db.db_path(str(tmp_path))).execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "projects" in tables


def test_check_disk_space_helper():
    with pytest.raises(CliError, match="Minimum 5GB disk space is required"):
        upgrade.check_disk_space(["/a", "/b"], free=lambda p: GIB if p == "/b" else 9 * GIB)
    upgrade.check_disk_space(["/a"], free=lambda p: 5 * GIB)
