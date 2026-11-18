import io
import json
import os
import stat
import subprocess
import sys
import time

import pytest

import build_archive
from appctl_core import catalog, cli_commands, db, file_cache, startup, system
from appctl_core.app import run
from appctl_core.command_tree import CommandTree
from conftest import prime_root

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAC_UPDATE_ERROR = ("Error: Self-update is not available. "
                    "Please use your system package manager to update.\n")

# A container runtime that logs every call, fails ``ps`` until it has been
# called $FAKE_STATE/ps-failures times, and lists resources from state files.
FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$FAKE_LOG"
if [ "$1" = "ps" ] && [ "$2" = "" ]; then
  count=$(cat "$FAKE_STATE/ps-count" 2>/dev/null || echo 0)
  count=$((count + 1))
  echo "$count" > "$FAKE_STATE/ps-count"
  failures=$(cat "$FAKE_STATE/ps-failures" 2>/dev/null || echo 0)
  [ "$count" -le "$failures" ] && exit 1
  exit 0
fi
case "$1 $2" in
  "ps -aq") cat "$FAKE_STATE/containers" 2>/dev/null; exit 0 ;;
  "network ls"|"volume ls"|"image ls") cat "$FAKE_STATE/$1s" 2>/dev/null; exit 0 ;;
  "compose version") echo 2.30.0; exit 0 ;;
esac
exit 0
"""
FAKE_COMPOSE = """#!/bin/sh
cat "$FAKE_STATE/compose-version" 2>/dev/null || echo 2.30.0
"""


class Tty(io.StringIO):
    def isatty(self):
        return True


class Fake:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.state = tmp_path / "state"
        self.state.mkdir()
        self.log = tmp_path / "docker.log"
        self.root = tmp_path / "root"
        self.install("docker", FAKE_DOCKER)
        self.install("docker-compose", FAKE_COMPOSE)
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(tmp_path),
                    "APPCTL_ROOT_DIR": str(self.root), "FAKE_LOG": str(self.log),
                    "FAKE_STATE": str(self.state),
                    "APPCTL_DISABLE_AUTO_CHECK_UPDATE": "1"}

    def install(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def call(self, *argv, env=None, stdin="", stdout=None, tree=None):
        out, err = stdout or io.StringIO(), io.StringIO()
        full = dict(self.env)
        for key, value in (env or {}).items():
            if value is None:
                full.pop(key, None)
            else:
                full[key] = value
        code = run(list(argv), full, out, err, cwd=str(self.tmp),
                   stdin=io.StringIO(stdin), tree=tree)
        return code, out.getvalue(), err.getvalue()

    def prime(self, version=None):
        prime_root(self.root)
        if version is not None:
            with db.open_database(str(self.root)) as store:
                store.update_option("version", version)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setattr(system, "RUNTIME_CHECK_DELAYS", (0, 0, 0))
    return Fake(tmp_path)


@pytest.fixture
def darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")


# --- system requirements ---------------------------------------------------------------

def test_requirements_met(fake):
    fake.prime()
    code, out, err = fake.call("site", "list")
    assert (code, err) == (0, "") and "main" in out
    assert fake.calls()[0] == "ps"


def test_runtime_retried_with_bounded_backoff(fake, monkeypatch):
    fake.prime()
    pauses = []
    monkeypatch.setattr(time, "sleep", pauses.append)
    monkeypatch.setattr(system, "RUNTIME_CHECK_DELAYS", (0.2, 0.4, 0.8))
    (fake.state / "ps-failures").write_text("2")
    code, _, err = fake.call("site", "list")
    assert (code, err) == (0, "")
    assert pauses == [0.2, 0.4]
    assert fake.calls().count("ps") == 3


def test_runtime_down_after_all_attempts(fake):
    fake.prime()
    (fake.state / "ps-failures").write_text("100")
    code, out, err = fake.call("site", "list")
    assert (code, out) == (1, "")
    assert err == ("Error: Container runtime is not installed or not running. Please "
                   "install and start the container runtime to run AppCtl.\n")
    assert fake.calls().count("ps") == 1 + len(system.RUNTIME_CHECK_DELAYS)


def test_runtime_error_has_package_manager_hint_on_macos(fake, darwin):
    fake.prime()
    (fake.state / "ps-failures").write_text("100")
    code, _, err = fake.call("site", "list")
    assert code == 1 and "brew install" in err


def test_compose_not_installed(fake):
    fake.prime()
    os.remove(fake.bin / "docker-compose")
    fake.install("docker", "#!/bin/sh\nexit 0\n")
    code, _, err = fake.call("site", "list", env={"PATH": str(fake.bin)})
    assert code == 1
    assert err == ("Error: Compose tool is not installed. "
                   "Please install the compose tool to run AppCtl.\n")


def test_compose_too_old(fake):
    fake.prime()
    (fake.state / "compose-version").write_text("1.29.2\n")
    code, _, err = fake.call("site", "list")
    assert code == 1
    assert err == "Error: AppCtl requires compose tool version 2.0.0 or newer (found 1.29.2).\n"
    (fake.state / "compose-version").write_text("v2.0.0\n")
    assert fake.call("site", "list")[0] == 0


def test_runtime_version_too_old(fake, monkeypatch):
    fake.prime()
    monkeypatch.setattr(system, "MIN_RUNTIME_VERSION", "99.0.0")
    code, _, err = fake.call("site", "list")
    assert code == 1 and err.startswith("Error: AppCtl requires Python 99.0.0 or newer")


@pytest.mark.parametrize("argv", [("cli", "version"), ("config", "get", "DB_NAME"),
                                  ("cfg", "get", "DB_NAME"), ("help",), ()])
def test_exempt_families_skip_checks(fake, argv):
    fake.prime()
    (fake.state / "ps-failures").write_text("100")
    code, _, err = fake.call(*argv)
    assert (code, err) == (0, "")
    assert fake.calls() == []


def test_unknown_command_is_reported_before_checks(fake):
    (fake.state / "ps-failures").write_text("100")
    code, _, err = fake.call("nosuch")
    assert code == 1 and "not a registered appctl command" in err
    assert fake.calls() == []


# --- first run -------------------------------------------------------------------------

def test_first_run_creates_store_and_reports(fake):
    code, out, err = fake.call("site", "list")
    assert (code, err) == (0, "")
    assert out.startswith("Success: AppCtl has been set up successfully.\n")
    with db.open_database(str(fake.root)) as store:
        assert store.get_option("version") == catalog.VERSION
    assert "Success" not in fake.call("site", "list")[1]


@pytest.mark.parametrize("argv,check", [
    (("cli", "version"), lambda out: out == f"{catalog.VERSION}\n"),
    (("cli", "info", "--format=json"), lambda out: json.loads(out)["version"]),
    (("cli", "param-dump"), lambda out: json.loads(out)),
    (("cli", "cmd-dump"), lambda out: json.loads(out)),
    (("cli", "alias", "--format=json"), lambda out: json.loads(out) == {}),
    (("cli", "has-command", "site"), lambda out: out == ""),
    (("site", "list", "--format=json"), lambda out: json.loads(out)),
    (("site", "create", "x", "--porcelain"), lambda out: out == "x\n"),
])
def test_first_run_preserves_machine_readable_output(fake, argv, check):
    code, out, err = fake.call(*argv)
    assert (code, err) == (0, "")
    assert check(out)
    with db.open_database(str(fake.root)) as store:
        assert store.get_option("version") == catalog.VERSION


def test_first_run_on_macos_explains_runtime_setup(fake, darwin):
    code, out, _ = fake.call("help")
    lines = out.splitlines()
    assert code == 0
    assert lines[0] == "Success: AppCtl has been set up successfully."
    assert "Docker Desktop" in lines[1] and str(fake.root) in lines[1]
    assert fake.call("cli", "version", env={"APPCTL_ROOT_DIR": str(fake.tmp / "r2")})[1] == (
        f"{catalog.VERSION}\n")


def test_completion_does_not_set_up(fake):
    code, out, _ = fake.call("cli", "completions", "--line=appctl cli ver", "--point=17")
    assert (code, out) == (0, "version\n")
    with db.open_database(str(fake.root)) as store:
        assert store.get_option("version") is False


# --- version comparison -------------------------------------------------------------------

def test_older_binary_warns_for_cli_commands(fake):
    fake.prime("9.0.0")
    code, out, err = fake.call("cli", "version")
    assert (code, out) == (0, f"{catalog.VERSION}\n")
    assert err == (f"Warning: AppCtl version {catalog.VERSION} is older than the version "
                   "9.0.0 used to set up this system.\n")
    with db.open_database(str(fake.root)) as store:
        assert store.get_option("version") == "9.0.0"


@pytest.mark.parametrize("argv", [("site", "list"), ("help",), ("config", "get", "DB_NAME")])
def test_older_binary_refuses_other_commands(fake, argv):
    fake.prime("9.0.0")
    code, out, err = fake.call(*argv)
    assert (code, out) == (1, "")
    assert err.startswith("Error: AppCtl version 1.0.0 is older than the version 9.0.0")
    assert "appctl cli update" in err


def test_older_binary_is_compared_semantically(fake):
    fake.prime("1.0.0-beta")
    assert fake.call("site", "list")[0] == 0
    fake.prime("1.0.10")
    catalog_version = catalog.VERSION
    assert catalog_version == "1.0.0"
    assert fake.call("site", "list")[0] == 1


def test_has_command_stays_silent_with_older_binary(fake):
    fake.prime("9.0.0")
    assert fake.call("cli", "has-command", "site") == (0, "", "")


def test_newer_binary_migrates(fake, monkeypatch):
    fake.prime("0.9.0")
    ran = []
    monkeypatch.setattr(catalog, "upgrader",
                        lambda *a: type("U", (), {"run": lambda self: ran.append(1)})())
    assert fake.call("site", "list")[0] == 0
    assert ran == [1]
    fake.prime()
    assert fake.call("site", "list")[0] == 0
    assert ran == [1]


def test_nightly_always_migrates(fake, monkeypatch):
    fake.prime("1.0.0-nightly")
    monkeypatch.setattr(catalog, "VERSION", "1.0.0-nightly")
    ran = []
    monkeypatch.setattr(catalog, "upgrader",
                        lambda *a: type("U", (), {"run": lambda self: ran.append(1)})())
    assert fake.call("site", "list")[0] == 0
    assert fake.call("site", "list")[0] == 0
    assert ran == [1, 1]


# --- releases fixtures -----------------------------------------------------------------

def releases_file(tmp_path, versions, extra=()):
    data = [{"tag_name": f"v{v}", "assets": [
        {"browser_download_url": f"https://example.com/{v}/appctl.pyz"}]} for v in versions]
    data += list(extra)
    path = tmp_path / "releases.json"
    path.write_text(json.dumps(data))
    return path.as_uri()


def check(fake, *args, versions=("0.9.0", "1.0.1", "1.0.2", "1.1.0", "1.2.0", "2.0.0"),
          extra=(), env=None):
    url = releases_file(fake.tmp, versions, extra)
    return fake.call("cli", "check-update", *args,
                     env=dict({"APPCTL_RELEASES_URL": url}, **(env or {})))


# --- check-update ----------------------------------------------------------------------

def test_check_update_lists_newest_of_each_type(fake):
    fake.prime()
    code, out, err = check(fake, "--format=json", extra=[
        {"tag_name": "3.0.0-beta", "prerelease": True, "assets": [
            {"browser_download_url": "https://example.com/beta.pyz"}]},
        {"tag_name": "v4.0.0", "draft": True, "assets": []}])
    assert (code, err) == (0, "")
    assert json.loads(out) == [
        {"version": "2.0.0", "update_type": "major",
         "package_url": "https://example.com/2.0.0/appctl.pyz"},
        {"version": "1.2.0", "update_type": "minor",
         "package_url": "https://example.com/1.2.0/appctl.pyz"},
        {"version": "1.0.2", "update_type": "patch",
         "package_url": "https://example.com/1.0.2/appctl.pyz"}]


@pytest.mark.parametrize("flags,expected", [
    (("--patch",), "1.0.2"), (("--minor",), "1.2.0"), (("--major",), "2.0.0"),
    (("--patch", "--major"), "2.0.0"), (("--major", "--patch"), "1.0.2"),
    (("--major", "--patch", "--minor"), "1.2.0"),
])
def test_check_update_last_filter_wins(fake, flags, expected):
    fake.prime()
    code, out, _ = check(fake, *flags, "--field=version")
    assert (code, out) == (0, f"{expected}\n")


def test_check_update_formats(fake):
    fake.prime()
    code, out, _ = check(fake)
    lines = out.splitlines()
    assert code == 0 and lines[0].split() == ["version", "update_type", "package_url"]
    assert len(lines) == 4
    code, out, _ = check(fake, "--minor")
    assert out.splitlines()[0].split() == ["version", "update_type", "package_url"]
    assert check(fake, "--format=count")[1] == "3\n"
    assert check(fake, "--format=csv", "--patch")[1] == (
        "version,update_type,package_url\n1.0.2,patch,https://example.com/1.0.2/appctl.pyz\n")
    yaml_out = check(fake, "--format=yaml", "--major")[1]
    assert yaml_out.startswith("---") and "version: 2.0.0" in yaml_out
    assert check(fake, "--format=json", "--fields=version,update_type", "--major")[1] == (
        '[\n    {\n        "version": "2.0.0",\n        "update_type": "major"\n    }\n]\n')
    code, _, err = check(fake, "--format=ids")
    assert code == 1 and err.startswith("Error: Invalid format: ids.")


def test_check_update_when_up_to_date(fake):
    fake.prime()
    versions = ("0.9.0", "1.0.0", "2.0.0")
    assert check(fake, versions=("0.9.0", "1.0.0")) == (
        0, "Success: AppCtl is at the latest version.\n", "")
    assert check(fake, "--minor", versions=versions) == (
        0, "Success: AppCtl is at the latest minor version.\n", "")
    assert check(fake, "--format=table", "--patch", versions=versions)[1] == (
        "Success: AppCtl is at the latest patch version.\n")
    assert check(fake, "--format=json", "--patch", versions=versions)[1] == "[]\n"
    assert check(fake, "--format=count", "--patch", versions=versions)[1] == "0\n"


def test_check_update_for_nightly_uses_nightly_channel(fake, monkeypatch):
    monkeypatch.setattr(catalog, "VERSION", "1.0.0-nightly.20261101")
    fake.prime()
    version_file = fake.tmp / "NIGHTLY_VERSION"
    version_file.write_text("1.0.0-nightly.20261111\n")
    env = {"APPCTL_NIGHTLY_VERSION_URL": version_file.as_uri(),
           "APPCTL_NIGHTLY_URL": "https://example.com/nightly.pyz",
           "APPCTL_RELEASES_URL": (fake.tmp / "missing.json").as_uri()}
    code, out, err = fake.call("cli", "check-update", "--format=json", env=env)
    assert (code, err) == (0, "")
    assert json.loads(out) == [{"version": "1.0.0-nightly.20261111", "update_type": "nightly",
                                "package_url": "https://example.com/nightly.pyz"}]
    version_file.write_text("1.0.0-nightly.20261101\n")
    assert fake.call("cli", "check-update", env=env)[1] == (
        "Success: AppCtl is at the latest version.\n")


def test_check_update_unreachable(fake):
    fake.prime()
    code, _, err = fake.call("cli", "check-update", env={
        "APPCTL_RELEASES_URL": (fake.tmp / "missing.json").as_uri()})
    assert code == 1 and err.startswith("Error: Failed to get the latest version from ")


# --- update ----------------------------------------------------------------------------

def build_release(tmp_path, version, name="release.pyz"):
    """A distribution archive reporting ``version``."""
    source = tmp_path / f"src-{version}"
    (source / "appctl_core").mkdir(parents=True)
    for entry in os.listdir(os.path.join(ROOT, "appctl_core")):
        src = os.path.join(ROOT, "appctl_core", entry)
        if entry == "__pycache__":
            continue
        dst = source / "appctl_core" / entry
        if os.path.isdir(src):
            import shutil
            shutil.copytree(src, dst, ignore=lambda *_: ["__pycache__"])
        else:
            dst.write_bytes(open(src, "rb").read())
    catalog_py = source / "appctl_core" / "catalog.py"
    catalog_py.write_text(catalog_py.read_text().replace(
        f'VERSION = "{catalog.VERSION}"', f'VERSION = "{version}"'))
    return build_archive.build(str(tmp_path / name), source=str(source))


@pytest.fixture
def updatable(fake):
    fake.prime()
    binary = fake.tmp / "installed" / "appctl.pyz"
    binary.parent.mkdir()
    binary.write_text("old binary")
    binary.chmod(0o751)
    fake.env["APPCTL_BINARY_PATH"] = str(binary)
    return binary


def test_update_on_macos_is_refused(fake, darwin):
    fake.prime()
    for flags in ((), ("--yes",), ("--stable",), ("--nightly", "--yes")):
        assert fake.call("cli", "update", *flags) == (1, "", MAC_UPDATE_ERROR)


def test_update_to_newest_release(fake, updatable):
    archive = build_release(fake.tmp, "1.2.0")
    url = releases_file(fake.tmp, ["1.0.1", "1.2.0"])
    data = json.loads(open(url[len("file://"):]).read())
    data[1]["assets"][0]["browser_download_url"] = "file://" + archive
    (fake.tmp / "releases.json").write_text(json.dumps(data))
    env = {"APPCTL_RELEASES_URL": url}
    code, out, err = fake.call("cli", "update", env=env, stdin="n\n")
    assert code == 0 and "Would you like to update to 1.2.0? [y/n]" in out
    assert updatable.read_text() == "old binary"
    code, out, err = fake.call("cli", "update", "--yes", env=env)
    assert (code, err) == (0, "")
    assert out.endswith("Success: Updated AppCtl to 1.2.0.\n")
    assert updatable.read_bytes() == open(archive, "rb").read()
    assert stat.S_IMODE(updatable.stat().st_mode) == 0o751
    assert os.listdir(updatable.parent) == ["appctl.pyz"]
    proc = subprocess.run([sys.executable, str(updatable), "cli", "version"],
                          capture_output=True, text=True,
                          env=dict(os.environ, APPCTL_ROOT_DIR=str(fake.tmp / "r3")))
    assert proc.stdout == "1.2.0\n"


def test_update_when_up_to_date(fake, updatable):
    env = {"APPCTL_RELEASES_URL": releases_file(fake.tmp, ["0.9.0", "1.0.0"])}
    assert fake.call("cli", "update", "--yes", env=env) == (
        0, "Success: AppCtl is at the latest version.\n", "")


def test_update_stable_and_nightly(fake, updatable):
    stable = build_release(fake.tmp, "1.5.0", "stable.pyz")
    nightly = build_release(fake.tmp, "1.6.0-nightly.20261111", "nightly.pyz")
    url = releases_file(fake.tmp, [], extra=[
        {"tag_name": "v1.5.0", "assets": [{"browser_download_url": "file://" + stable}]},
        {"tag_name": "v0.5.0", "assets": [{"browser_download_url": "file:///nope.pyz"}]}])
    env = {"APPCTL_RELEASES_URL": url, "APPCTL_NIGHTLY_URL": "file://" + nightly}
    code, out, _ = fake.call("cli", "update", "--nightly", "--yes", env=env)
    assert code == 0 and out.endswith("Success: Updated AppCtl to 1.6.0-nightly.20261111.\n")
    code, out, _ = fake.call("cli", "update", "--stable", "--yes", env=env)
    assert code == 0 and out.endswith("Success: Updated AppCtl to 1.5.0.\n")
    assert updatable.read_bytes() == open(stable, "rb").read()


@pytest.mark.parametrize("content", [b"not an archive", None])
def test_failed_validation_keeps_old_binary(fake, updatable, content):
    broken = fake.tmp / "broken.pyz"
    if content is None:
        import zipfile
        with zipfile.ZipFile(broken, "w") as bundle:
            bundle.writestr("__main__.py", "import sys\nsys.exit(3)\n")
    else:
        broken.write_bytes(content)
    env = {"APPCTL_NIGHTLY_URL": broken.as_uri()}
    code, out, err = fake.call("cli", "update", "--nightly", "--yes", env=env)
    assert code == 1 and "Success" not in out
    assert err.startswith("Error: The downloaded update is broken")
    assert updatable.read_text() == "old binary"
    assert os.listdir(updatable.parent) == ["appctl.pyz"]


def test_checksum_mismatch_keeps_old_binary(fake, updatable):
    archive = build_release(fake.tmp, "1.2.0")
    with open(archive + ".sha256", "w") as handle:
        handle.write("0" * 64 + "  appctl.pyz\n")
    env = {"APPCTL_NIGHTLY_URL": "file://" + archive}
    code, _, err = fake.call("cli", "update", "--nightly", "--yes", env=env)
    assert code == 1 and "checksum" in err
    assert updatable.read_text() == "old binary"


def test_update_requires_writable_binary(fake, updatable):
    updatable.chmod(0o444)
    if os.access(updatable, os.W_OK):
        pytest.skip("running as root")
    code, _, err = fake.call("cli", "update", "--nightly", "--yes")
    assert code == 1 and "is not writable by current user" in err


# --- auto-update checks -------------------------------------------------------------------

@pytest.fixture
def auto(fake, updatable, monkeypatch):
    calls = []
    monkeypatch.setattr(cli_commands, "self_update", lambda out, env, **kw: calls.append(kw))
    fake.env.pop("APPCTL_DISABLE_AUTO_CHECK_UPDATE")
    fake.env["APPCTL_RELEASES_URL"] = releases_file(fake.tmp, ["1.0.1"])
    cache = file_cache.from_env(fake.env, str(fake.root))

    def last_check():
        value = cache.read(startup.UPDATE_CHECK_KEY)
        return None if value is False else int(value)

    def age(days):
        cache.write(startup.UPDATE_CHECK_KEY, str(int(time.time() - days * 86400 - 60)))

    return calls, last_check, age


def test_first_auto_check_only_records_time(fake, auto):
    calls, last_check, age = auto
    assert fake.call("cli", "version", stdout=Tty())[0] == 0
    assert last_check() is not None and calls == []
    assert fake.call("cli", "version", stdout=Tty())[0] == 0
    assert calls == []


def test_auto_check_after_interval_triggers_update(fake, auto):
    calls, last_check, age = auto
    age(1)
    assert fake.call("cli", "version", stdout=Tty())[1] == "1.0.0\n"
    assert calls == [{}]
    assert time.time() - last_check() < 60
    assert fake.call("cli", "version", stdout=Tty())[0] == 0
    assert calls == [{}]


def test_auto_check_interval_override(fake, auto):
    calls, _, age = auto
    age(2)
    fake.call("cli", "version", stdout=Tty(), env={"APPCTL_AUTO_CHECK_UPDATE_DAYS": "3"})
    assert calls == []
    age(3)
    fake.call("cli", "version", stdout=Tty(), env={"APPCTL_AUTO_CHECK_UPDATE_DAYS": "3"})
    assert calls == [{}]


def test_auto_check_without_updates(fake, auto):
    calls, last_check, age = auto
    fake.env["APPCTL_RELEASES_URL"] = releases_file(fake.tmp, ["0.9.0"])
    age(5)
    fake.call("cli", "version", stdout=Tty())
    assert calls == [] and time.time() - last_check() < 60


@pytest.mark.parametrize("case", ["disabled", "not-a-tty", "read-only"])
def test_auto_check_skipped(fake, auto, updatable, case):
    calls, last_check, age = auto
    env, stdout = {}, Tty()
    if case == "disabled":
        env = {"APPCTL_DISABLE_AUTO_CHECK_UPDATE": "1"}
    elif case == "not-a-tty":
        stdout = io.StringIO()
    else:
        updatable.chmod(0o444)
        if os.access(updatable, os.W_OK):
            pytest.skip("running as root")
    fake.call("cli", "version", stdout=stdout, env=env)
    assert last_check() is None
    age(10)
    fake.call("cli", "version", stdout=stdout, env=env)
    assert calls == []


# --- runtime binary ---------------------------------------------------------------------

def test_runtime_binary_resolution(monkeypatch):
    env = {"APPCTL_RUNTIME_BIN": "/opt/py", "APPCTL_RUNTIME_BIN_USED": "/usr/py"}
    assert system.runtime_binary(env) == "/opt/py"
    assert system.runtime_binary({"APPCTL_RUNTIME_BIN_USED": "/usr/py"}) == "/usr/py"
    assert system.runtime_binary({}) == sys.executable
    monkeypatch.setattr(sys, "executable", "")
    assert system.runtime_binary({}) == "python3"


def test_children_use_resolved_runtime_binary(fake):
    fake.prime()
    from appctl_core import process
    from appctl_core.output import Output
    launcher = process.Launcher({}, dict(fake.env, APPCTL_RUNTIME_BIN=sys.executable),
                                str(fake.tmp), Output(io.StringIO(), io.StringIO()))
    assert launcher.argv("cli version")[0] == sys.executable
    assert launcher.environment()["APPCTL_RUNTIME_BIN_USED"] == sys.executable
    info = launcher.runcommand("cli info --format=json", parse="json")
    assert info["runtime_binary"] == sys.executable


# --- version and info -------------------------------------------------------------------

def test_version(fake):
    fake.prime()
    assert fake.call("cli", "version") == (0, f"{catalog.VERSION}\n", "")
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "appctl.py"), "--version"],
                          capture_output=True, text=True,
                          env=dict(os.environ, APPCTL_ROOT_DIR=str(fake.root)))
    assert proc.stdout == f"{catalog.VERSION}\n"


def test_info_list_and_json_agree(fake):
    fake.prime()
    code, out, _ = fake.call("cli", "info")
    rows = dict(line.split(":\t", 1) for line in out.splitlines())
    data = json.loads(fake.call("cli", "info", "--format=json")[1])
    assert code == 0 and len(rows) == len(data)
    assert rows["AppCtl version"] == data["version"] == catalog.VERSION
    assert rows["AppCtl root dir"] == data["root_dir"] == str(fake.root)
    assert rows["Python binary"] == data["runtime_binary"]
    assert rows["Python version"] == data["runtime_version"]
    assert rows["OS"] == data["os"] and data["os"]
    assert data["global_config_path"] == str(fake.root / "config" / "config.yml")
    assert data["stored_version"] == catalog.VERSION
    assert data["packages_dir"] is None and rows["AppCtl packages dir"] == ""
    (fake.root / "packages").mkdir()
    data = json.loads(fake.call("cli", "info", "--format=json")[1])
    assert data["packages_dir"] == str(fake.root / "packages")
    data = json.loads(fake.call("cli", "info", "--format=json",
                                env={"APPCTL_RUNTIME_BIN": "/opt/python"})[1])
    assert data["runtime_binary"] == "/opt/python"
    code, _, err = fake.call("cli", "info", "--format=xml")
    assert code == 1 and err.startswith("Error: Invalid format: xml.")


# --- dumps ------------------------------------------------------------------------------

def test_param_dump(fake):
    fake.prime()
    data = json.loads(fake.call("cli", "param-dump")[1])
    assert list(data) == sorted(data)
    assert data["url"]["runtime"] == "[--url=<url>]" and "current" not in data["url"]
    data = json.loads(fake.call("cli", "param-dump", "--with-values", "--url=example.org")[1])
    assert data["url"]["current"] == "example.org"
    assert data["locale"]["current"] == "en_US"
    code, out, _ = fake.call("cli", "param-dump", "--format=var_export")
    assert code == 0 and out.startswith("array (\n  'admin-email' => \n  array (\n")
    assert "    'runtime' => '[--url=<url>]',\n" in out and out.endswith(")\n")
    code, _, err = fake.call("cli", "param-dump", "--format=xml")
    assert code == 1 and "Supported formats: json, var_export" in err


def test_cmd_dump(fake):
    fake.prime()
    data = json.loads(fake.call("cli", "cmd-dump")[1])
    assert data["name"] == "appctl" and "synopsis" not in data

    def walk(entry, prefix):
        assert {"name", "description", "longdesc", "subcommands"} <= set(entry)
        names = [c["name"] for c in entry["subcommands"]]
        assert names == sorted(names)
        if not entry["subcommands"]:
            assert "synopsis" in entry
        for child in entry["subcommands"]:
            walk(child, prefix + [child["name"]])

    walk(data, [])
    cli = next(c for c in data["subcommands"] if c["name"] == "cli")
    update = next(c for c in cli["subcommands"] if c["name"] == "update")
    assert update["synopsis"].startswith("[--stable] [--nightly] [--yes]")
    assert update["subcommands"] == []


def test_has_command(fake):
    fake.prime()
    assert fake.call("cli", "has-command", "site create") == (0, "", "")
    assert fake.call("cli", "has-command", "site", "create") == (0, "", "")
    assert fake.call("cli", "has-command", "site") == (0, "", "")
    assert fake.call("cli", "has-command", "site nosuch") == (1, "", "")
    assert fake.call("cli", "has-command", "nosuch") == (1, "", "")
    (fake.tmp / "appctl.yml").write_text("disabled_commands: [site]\n")
    assert fake.call("cli", "has-command", "site create") == (1, "", "")


def test_aliases(fake):
    fake.prime()
    (fake.tmp / "appctl.yml").write_text("'@prod':\n  ssh: prod.example.com\n'@dev':\n  path: /srv\n")
    code, out, _ = fake.call("cli", "alias")
    assert code == 0 and out.startswith("---\n'@all':")
    assert fake.call("cli", "aliases") == (code, out, "")
    data = json.loads(fake.call("cli", "alias", "--format=json")[1])
    assert list(data) == ["@all", "@dev", "@prod"]
    assert data["@prod"] == {"ssh": "prod.example.com"}
    assert fake.call("cli", "aliases", "--format=json")[1] == fake.call(
        "cli", "alias", "--format=json")[1]


# --- self-uninstall ------------------------------------------------------------------

def test_self_uninstall_removes_everything(fake):
    fake.prime()
    project = fake.tmp / "projects" / "one"
    project.mkdir(parents=True)
    with db.open_database(str(fake.root)) as store:
        store.add_project("one", str(project))
    for name, ids in (("containers", "c1\nc2\n"), ("networks", "n1\n"),
                      ("volumes", "v1\n"), ("images", "i1\n")):
        (fake.state / name).write_text(ids)
    code, out, err = fake.call("cli", "self-uninstall", "--yes")
    assert (code, err) == (0, "")
    assert out == "Success: AppCtl and all its data has been removed successfully.\n"
    calls = fake.calls()
    label = "label=org.label-schema.vendor=AppCtl"
    assert calls == ["ps", f"ps -aq --filter {label}", "rm -f c1 c2",
                     f"network ls -q --filter {label}", "network rm n1",
                     f"volume ls -q --filter {label}", "volume rm -f v1",
                     f"image ls -q --filter {label}", "image rm -f i1"]
    assert not fake.root.exists() and not project.exists()
    assert (fake.bin / "docker").exists()


def test_self_uninstall_needs_confirmation(fake):
    fake.prime()
    code, out, err = fake.call("cli", "self-uninstall", stdin="yes\n")
    assert code == 0 and "[y/n]" in out and "irreversible" in out
    assert err == "Warning: Operation cancelled.\n"
    assert fake.root.exists() and fake.calls() == ["ps"]
    code, out, _ = fake.call("cli", "self-uninstall", stdin="y\n")
    assert code == 0 and not fake.root.exists()


def test_self_uninstall_aborts_when_dependencies_are_down(fake):
    fake.prime()
    (fake.state / "ps-failures").write_text("100")
    code, out, err = fake.call("cli", "self-uninstall", "--yes")
    assert (code, out) == (1, "")
    assert err.endswith("Error: Unable to proceed with uninstallation. "
                        "Seems there is a dependency down.\n")
    assert fake.root.exists()
    assert set(fake.calls()) == {"ps"}


def test_self_uninstall_removes_archive(fake, monkeypatch):
    fake.prime()
    archive = fake.tmp / "appctl.pyz"
    archive.write_text("binary")
    monkeypatch.setattr(system, "archive_path", lambda: str(archive))
    assert fake.call("cli", "self-uninstall", "--yes")[0] == 0
    assert not archive.exists()


# --- tab completion --------------------------------------------------------------------

def complete(fake, line, point=None, shell=None, tree=None):
    args = ["cli", "completions", f"--line={line}",
            f"--point={len(line) if point is None else point}"]
    if shell:
        args.append(f"--shell={shell}")
    code, out, err = fake.call(*args, tree=tree)
    assert (code, err) == (0, "")
    return out.splitlines()


def test_completion_of_commands_and_aliases(fake):
    fake.prime()
    (fake.tmp / "appctl.yml").write_text("'@prod':\n  ssh: prod\n'@dev':\n  path: /srv\n")
    root = complete(fake, "appctl ")
    assert root[:3] == ["@all", "@dev", "@prod"]
    assert {"cli", "site", "help", "config"} <= set(root)
    assert root == sorted(root, key=str.casefold)
    assert complete(fake, "appctl @p") == ["@prod"]
    assert complete(fake, "appctl @prod si") == ["site"]
    assert "@prod" not in complete(fake, "appctl @prod ")
    assert complete(fake, "appctl help si") == ["site"]
    assert complete(fake, "appctl site c") == ["config", "create"]
    assert complete(fake, "appctl site new") == []
    assert complete(fake, "appctl nosuch ") == []


def test_completion_of_options(fake):
    fake.prime()
    options = complete(fake, "appctl site create foo --")
    assert options == sorted(options, key=str.casefold)
    assert {"--type=", "--title=", "--private", "--porcelain", "--url=", "--quiet"} <= set(
        options)
    assert "--type=" not in complete(fake, "appctl site create foo --type=x --")
    assert complete(fake, "appctl cli check-update --ma") == ["--major"]
    assert complete(fake, "appctl cli update --st") == ["--stable"]


def test_completion_uses_cursor_point(fake):
    fake.prime()
    line = "appctl site create foo"
    assert complete(fake, line, point=len("appctl si")) == ["site"]
    assert complete(fake, line, point=len("appctl site cr")) == ["create"]
    assert complete(fake, line, point=999) == []


def test_zsh_completion_has_descriptions(fake):
    fake.prime()
    (fake.tmp / "appctl.yml").write_text("'@prod':\n  ssh: prod\n")
    lines = complete(fake, "appctl ", shell="zsh")
    assert all(":" in line and line.split(":", 1)[1] for line in lines)
    assert "site:Creates, deletes, empties, archives, and lists sites." in lines
    assert lines[0].startswith("@all:")
    assert any(l.startswith("@prod:") for l in lines)
    opts = complete(fake, "appctl cli update --y", shell="zsh")
    assert opts == ["--yes:--yes"]
    code, _, err = fake.call("cli", "completions", "--line=appctl ", "--point=7",
                             "--shell=fish")
    assert code == 1 and "Invalid shell: fish" in err


def test_completion_file_marker(fake):
    fake.prime()
    tree = CommandTree()
    catalog.register_all(tree)
    tree.register("import", lambda ctx: 0, synopsis="<file> [--dry-run]",
                  description="Imports a file.")
    assert complete(fake, "appctl import ", tree=tree) == ["<file>"]
    assert complete(fake, "appctl im", tree=tree) == ["import"]


def test_completion_is_not_logged(fake):
    fake.prime()
    complete(fake, "appctl si")
    log = fake.root / "logs" / "appctl.log"
    assert not log.exists() or "cli completions" not in log.read_text()
    fake.call("cli", "version")
    assert log.exists()
    before = log.read_text()
    complete(fake, "appctl cli ")
    assert log.read_text() == before
