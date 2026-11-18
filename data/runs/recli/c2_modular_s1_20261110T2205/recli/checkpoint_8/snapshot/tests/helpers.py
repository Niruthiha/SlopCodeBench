"""Shared fixtures: a fake container runtime and an already set-up appctl root."""

import atexit
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "appctl.py")

# Responds to everything; reports a compose tool recent enough for the requirement checks.
FAKE_DOCKER = """#!/bin/sh
case "$*" in
  "compose version"*) echo "${FAKE_COMPOSE_VERSION:-2.29.7}"; exit 0 ;;
esac
exit 0
"""

_bin_dir = None


def fake_bin_dir():
    """A directory holding the fake ``docker`` binary, created once per test run."""
    global _bin_dir
    if _bin_dir is None:
        _bin_dir = tempfile.mkdtemp(prefix="appctl-fake-bin-")
        atexit.register(shutil.rmtree, _bin_dir, True)
        path = os.path.join(_bin_dir, "docker")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(FAKE_DOCKER)
        os.chmod(path, 0o755)
    return _bin_dir


def runtime_env(env=None, **extra):
    """``env`` (default: ``os.environ``) with the fake container runtime first on PATH."""
    env = dict(os.environ if env is None else env, **extra)
    env["PATH"] = fake_bin_dir() + os.pathsep + env.get("PATH", "")
    return env


def initialize(env, cwd=None):
    """Complete the first run so later invocations only print their own output."""
    subprocess.run([sys.executable, SCRIPT, "cli", "version"], env=env, cwd=cwd,
                   capture_output=True, check=True)
