import io
import os
import stat
import subprocess
import sys

import pytest

from appctl_core import containers
from appctl_core.app import run
from appctl_core.errors import CliError
from appctl_core.output import Output
from conftest import prime_root

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A fake container runtime: logs every call and answers from state files.
FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$FAKE_LOG"
case "$1 $2" in
  "inspect --type=container")
    state="$FAKE_STATE/container-$5"
    [ -f "$state" ] || exit 1
    cat "$state"; exit 0 ;;
  "volume inspect") [ -f "$FAKE_STATE/volume-$3" ] || exit 1; exit 0 ;;
  "network inspect") [ -f "$FAKE_STATE/network-$3" ] || exit 1; exit 0 ;;
  "network connect"|"network disconnect") [ -f "$FAKE_STATE/fail" ] && exit 1; exit 0 ;;
  "info --format") echo /data/docker; exit 0 ;;
esac
exit 0
"""


@pytest.fixture
def fake(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "docker"
    script.write_text(FAKE_DOCKER)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    state = tmp_path / "state"
    state.mkdir()
    log = tmp_path / "docker.log"
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "FAKE_LOG": str(log),
           "FAKE_STATE": str(state), "APPCTL_ROOT_DIR": str(tmp_path / "root")}

    class Fake:
        pass

    f = Fake()
    f.env, f.state, f.log, f.tmp = env, state, log, tmp_path
    f.calls = lambda: log.read_text().splitlines() if log.exists() else []
    return f


def runtime(fake, config=None, platform="linux"):
    out, err = io.StringIO(), io.StringIO()
    rt = containers.Runtime(out=Output(out, err), env=fake.env, cwd=str(fake.tmp),
                            config=config or {}, platform=platform)
    return rt, out, err


def call(tmp_path, *argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    env = env or {"APPCTL_ROOT_DIR": str(tmp_path / "root")}
    prime_root(env["APPCTL_ROOT_DIR"])
    code = run(list(argv), env, out, err, cwd=str(tmp_path), stdin=io.StringIO(""))
    return code, out.getvalue(), err.getvalue()


def write_project(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  web:\n    image: nginx\n  db:\n    image: mariadb\n"
        "  cache:\n    image: redis\n")
    return tmp_path


# --- compose merging -------------------------------------------------------------

def test_services_listed_in_configuration_order(tmp_path):
    write_project(tmp_path)
    prime_root(tmp_path / "r")
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "appctl.py"), "site",
                           "config", "--services"], cwd=tmp_path, capture_output=True,
                          text=True, env=dict(os.environ, APPCTL_ROOT_DIR=str(tmp_path / "r")))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "web\ndb\ncache\n"


def test_discovered_overrides_are_merged_deterministically(tmp_path):
    write_project(tmp_path)
    user = tmp_path / "user-docker-compose"
    user.mkdir()
    (user / "b.yml").write_text("services:\n  zz:\n    image: b\n")
    (user / "a.yml").write_text("services:\n  aa:\n    image: a\n  web:\n    ports: ['80:80']\n")
    (user / "notes.txt").write_text("services:\n  ignored:\n    image: x\n")
    (tmp_path / "docker-compose-custom.yml").write_text("services:\n  custom:\n    image: c\n")
    files = containers.compose_files(str(tmp_path))
    assert [os.path.relpath(f, tmp_path) for f in files] == [
        "docker-compose.yml", "docker-compose-custom.yml",
        os.path.join("user-docker-compose", "a.yml"),
        os.path.join("user-docker-compose", "b.yml")]
    code, out, _ = call(tmp_path, "site", "config", "--services")
    assert code == 0 and out == "web\ndb\ncache\ncustom\naa\nzz\n"


def test_custom_compose_replaces_discovery(tmp_path):
    write_project(tmp_path)
    (tmp_path / "docker-compose-custom.yml").write_text("services:\n  discovered:\n    image: c\n")
    (tmp_path / "mine.yml").write_text("services:\n  mine:\n    image: m\n")
    (tmp_path / "appctl.yml").write_text("custom-compose: mine.yml\n")
    assert call(tmp_path, "site", "config", "--services")[1] == "web\ndb\ncache\nmine\n"


def test_missing_custom_compose_warns_and_falls_back(tmp_path):
    write_project(tmp_path)
    (tmp_path / "appctl.yml").write_text("custom-compose: missing.yml\n")
    code, out, err = call(tmp_path, "site", "config", "--services")
    assert code == 0 and out == "web\ndb\ncache\n"
    assert err == ("Warning: File: missing.yml does not exist. "
                   "Falling back to default compose file.\n")


def test_service_exists(fake):
    write_project(fake.tmp)
    rt, _, _ = runtime(fake)
    assert rt.service_exists(str(fake.tmp), "db")
    assert not rt.service_exists(str(fake.tmp), "nope")
    assert call(fake.tmp, "site", "has-service", "web")[0] == 0
    assert call(fake.tmp, "site", "has-service", "nope")[0] == 1


# --- containers -----------------------------------------------------------------------

def test_runtime_missing(tmp_path):
    env = {"PATH": str(tmp_path / "empty"), "APPCTL_ROOT_DIR": str(tmp_path / "root")}
    code, out, err = call(tmp_path, "container", "status", "x", env=env)
    assert (code, out) == (1, "")
    assert err.startswith("Error: Container runtime is not installed or not running. ")


def test_runtime_disappearing_after_the_check(tmp_path, fake):
    rt, _, _ = runtime(fake)
    rt.env["PATH"] = str(tmp_path / "empty")
    with pytest.raises(CliError, match="^Container runtime is not installed. "):
        rt.run(["ps"])


def test_status_and_boot(fake):
    rt, _, _ = runtime(fake)
    assert rt.container_status("app") is None
    (fake.state / "container-app").write_text("false\n")
    assert rt.container_status("app") == "exited"
    assert rt.boot_container("app") is True
    assert fake.calls()[-1] == "start app"
    (fake.state / "container-app").write_text("true\n")
    assert rt.container_status("app") == "running"
    before = len(fake.calls())
    assert rt.boot_container("app", create=["run", "app"]) is True
    assert len(fake.calls()) == before + 1
    assert rt.boot_container("other", create=["create", "other"]) is True
    assert fake.calls()[-1] == "create other"


def test_start_stop_restart(fake):
    rt, _, _ = runtime(fake)
    assert rt.start_container("a") and rt.stop_container("a") and rt.restart_container("a")
    assert fake.calls() == ["start a", "stop a", "restart a"]


def test_up_down_exec(fake):
    project = write_project(fake.tmp)
    base = str(project / "docker-compose.yml")
    rt, _, _ = runtime(fake)
    rt.compose_up(str(project), ["web"])
    rt.compose_down(str(project))
    rt.compose_exec(str(project), "web", "ls -l", user="www-data")
    prefix = f"compose -p {containers.project_prefix(project.name)} -f {base}"
    assert fake.calls() == [f"{prefix} up -d web",
                            f"{prefix} down --volumes --remove-orphans",
                            f"{prefix} exec --user=www-data web ls -l"]
    rt, _, _ = runtime(fake, config={"skip-tty": True})
    rt.compose_exec(str(project), "web", "echo hi", shell="bash", shell_wrapper=True)
    assert fake.calls()[-1] == f"{prefix} exec -T web bash -c echo hi"


def test_skip_tty_from_config_file(fake):
    write_project(fake.tmp)
    (fake.tmp / "appctl.yml").write_text("skip-tty: true\n")
    code, _, err = call(fake.tmp, "site", "exec", "web", "true", env=fake.env)
    assert code == 0, err
    assert " exec -T web true" in fake.calls()[-1]


# --- volumes and networks ------------------------------------------------------------

def test_create_volumes(fake):
    rt, _, err = runtime(fake)
    (fake.state / "volume-mysite_exists").write_text("")
    link = fake.tmp / "sites" / "mysite" / "htdocs"
    created = rt.create_volumes("my-site", [
        {"name": "htdocs", "path_to_symlink": str(link), "container_path": "/var/www"},
        {"name": "skipped", "skip_volume": True, "container_path": "/x"},
        {"name": "exists", "container_path": "/y"},
    ])
    assert created == ["mysite_htdocs"]
    assert ("volume create --label org.label-schema.vendor=AppCtl "
            "--label io.appctl.project=my-site mysite_htdocs") in fake.calls()
    assert not any("skipped" in c for c in fake.calls())
    assert os.readlink(link) == "/data/docker/volumes/mysite_htdocs/_data"
    assert err.getvalue() == ""


def test_mounting_volumes_per_platform():
    volumes = [
        {"name": "htdocs", "path_to_symlink": "/s/htdocs", "container_path": "/var/www"},
        {"name": "logs", "path_to_symlink": "/s/logs", "container_path": "/logs",
         "skip_darwin": True},
        {"name": "conf", "path_to_symlink": "/s/conf", "container_path": "/conf",
         "skip_linux": True},
    ]
    assert containers.mounting_volumes(volumes, "linux") == ["htdocs:/var/www", "logs:/logs"]
    assert containers.mounting_volumes(volumes, "darwin") == ["/s/htdocs:/var/www",
                                                              "/s/conf:/conf"]


def test_networks(fake):
    rt, out, err = runtime(fake)
    assert rt.create_network("my.site")
    assert fake.calls()[-1] == ("network create --label org.label-schema.vendor=AppCtl "
                                "--label io.appctl.project=my.site my.site")
    assert rt.network_exists("my.site") is False
    (fake.state / "network-my.site").write_text("")
    assert rt.network_exists("my.site") is True
    assert rt.remove_network("my.site") and fake.calls()[-1] == "network rm my.site"
    rt.connect_network("my.site", "proxy")
    assert out.getvalue() == "Success: Site connected to proxy.\n"
    rt.disconnect_network("my.site", "proxy")
    assert "Disconnected from Docker network of proxy" in out.getvalue()
    (fake.state / "fail").write_text("")
    with pytest.raises(CliError, match=r"^There was some error connecting to proxy\.$"):
        rt.connect_network("my.site", "proxy")
    assert rt.disconnect_network("my.site", "proxy") is False
    assert err.getvalue() == "Warning: Error in disconnecting from Docker network of proxy\n"


def test_prefix_is_deterministic():
    assert containers.project_prefix("My-Site.example.com") == "mysiteexamplecom"
    assert containers.volume_name("a.b", {"name": "db"}) == "ab_db"
