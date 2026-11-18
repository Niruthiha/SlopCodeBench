import os
import stat

import pytest

# A container runtime and compose tool that are installed and responsive, so
# that commands checking the host requirements can run.
FAKE_DOCKER = """#!/bin/sh
case "$1 $2" in
  "compose version") echo 2.30.0; exit 0 ;;
esac
exit 0
"""
FAKE_COMPOSE = """#!/bin/sh
echo 2.30.0
"""


@pytest.fixture(autouse=True)
def host_tools(tmp_path_factory, monkeypatch):
    bin_dir = tmp_path_factory.mktemp("host-bin")
    for name, body in (("docker", FAKE_DOCKER), ("docker-compose", FAKE_COMPOSE)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))
    monkeypatch.setenv("APPCTL_DISABLE_AUTO_CHECK_UPDATE", "1")
    return bin_dir


def prime_root(root):
    """Record the current version in ``root`` so that the next invocation
    is not a first run."""
    from appctl_core import catalog, db
    with db.open_database(str(root)) as store:
        store.update_option("version", catalog.VERSION)
    return root


@pytest.fixture(autouse=True)
def primed_home(host_tools):
    """The default root (below ``$HOME``) has already been set up."""
    return prime_root(os.path.join(os.environ["HOME"], ".appctl"))
