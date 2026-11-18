import io
import json
import os
import sys
import tarfile
import time
import zipfile

import pytest

from appctl_core import file_cache, process
from appctl_core.app import run
from appctl_core.output import Output
from conftest import prime_root

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def call(tmp_path, *argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    full_env = {"APPCTL_ROOT_DIR": str(tmp_path / "root"), "PATH": os.environ.get("PATH", "")}
    full_env.update(env or {})
    code = run(list(argv), full_env, out, err, cwd=str(tmp_path), stdin=io.StringIO(""))
    return code, out.getvalue(), err.getvalue()


def debug_output():
    err = io.StringIO()
    return Output(io.StringIO(), err, debug=True), err


# --- process execution ---------------------------------------------------------

def test_run_exposes_outputs_code_and_runtime():
    out, err = debug_output()
    result = process.run(["sh", "-c", "echo out; echo problem >&2; exit 3"], out=out)
    assert (result.stdout, result.stderr, result.return_code) == ("out\n", "problem\n", 3)
    assert result.run_time >= 0
    lines = err.getvalue().splitlines()
    assert lines[0].startswith("Debug (process): Running command: sh -c ")
    assert lines[1].startswith("Debug (process): STDOUT: out")
    assert lines[2].startswith("Debug (process): STDERR: problem")
    assert lines[3].startswith("Debug (process): Return code: 3")


def test_empty_outputs_are_not_logged():
    out, err = debug_output()
    process.run("true", out=out)
    assert "STDOUT" not in err.getvalue() and "STDERR" not in err.getvalue()


def test_run_check_and_logging():
    out, err = debug_output()
    assert process.run_check("true", out=out) is True
    assert process.run_check(["false"], out=out) is False
    assert "Running command: false" in err.getvalue()


def test_obfuscation_hides_secret_in_debug_only():
    out, err = debug_output()
    result = process.run("echo --password=s3cret", out=out, obfuscate_list=["s3cret"])
    assert "s3cret" not in err.getvalue()
    assert "Running command: echo --password=******" in err.getvalue()
    assert result.stdout == "--password=s3cret\n"


def test_exit_code_minus_one_warns():
    out, err = debug_output()
    result = process.run(["sh", "-c", "kill -HUP $$"], out=out)
    assert result.return_code == -1
    assert "Warning: Spawned process returned exit code -1" in err.getvalue()
    assert "signal handling configuration" in err.getvalue()


def test_launcher_preserves_runtime_and_parses_json(tmp_path):
    config = tmp_path / "custom.yml"
    env = {"APPCTL_ROOT_DIR": str(tmp_path / "root"), "PATH": os.environ.get("PATH", "")}
    launcher = process.Launcher({"path": "/srv/app", "quiet": True, "color": False},
                                env, str(tmp_path), Output(io.StringIO(), io.StringIO()),
                                config_path=str(config))
    info = launcher.runcommand("cli info --format=json", parse="json")
    assert info["path"] == "/srv/app" and info["quiet"] is True and info["color"] is False
    assert info["global_config_path"] == str(config)
    assert launcher.launch_self("cli version", exit_on_error=False) == 0
    detailed = launcher.launch_self("nosuch", exit_on_error=False, return_detailed=True)
    assert detailed.return_code == 1 and "nosuch" in detailed.stderr


# --- file cache ------------------------------------------------------------------

def test_cache_location(tmp_path):
    assert file_cache.cache_dir({"APPCTL_CACHE_DIR": "/x/c"}, "/r") == "/x/c"
    assert file_cache.cache_dir({}, "/r") == os.path.join("/r", ".cache") + os.sep
    code, _, err = call(tmp_path, "cli", "version")
    assert code == 0 and err == "" and (tmp_path / "root" / ".cache").is_dir()
    custom = tmp_path / "custom" / "cache"
    assert call(tmp_path, "cli", "version", env={"APPCTL_CACHE_DIR": str(custom)})[0] == 0
    assert custom.is_dir()


def test_uncreatable_cache_dir_warns_and_disables(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    target = str(blocker / "cache")
    code, out, err = call(tmp_path, "cli", "version", env={"APPCTL_CACHE_DIR": target})
    assert code == 0 and out == "1.0.0\n"
    assert err == f"Warning: Failed to create directory '{target}': Not a directory.\n"
    cache = file_cache.FileCache(target)
    assert not cache.is_enabled() and cache.read("k") is False and not cache.write("k", "v")


def test_cache_read_write_and_expiry(tmp_path):
    cache = file_cache.FileCache(str(tmp_path / "c"), ttl=100)
    assert cache.read("missing") is False
    assert cache.write("core/pkg 1.zip", "data")
    assert cache.read("core/pkg 1.zip") == "data"
    path = cache.filename("core/pkg 1.zip")
    assert abs(os.path.getmtime(path) - time.time()) < 5
    old = time.time() - 500
    os.utime(path, (old, old))
    assert cache.read("core/pkg 1.zip") is False
    assert not os.path.exists(path)


def test_key_sanitization():
    keys = ["a b", "a-b", "a/b", "a\\b", "../x", "https://h.example/p.zip?v=1", "A", ""]
    sanitized = [file_cache.sanitize_key(k) for k in keys]
    assert sanitized == [file_cache.sanitize_key(k) for k in keys]
    for value in sanitized:
        assert value and all(p not in ("", ".", "..") for p in value.split("/"))
        assert all(c.isalnum() or c in "._-~/" for c in value)
    assert sanitized[0] != sanitized[1]
    assert file_cache.sanitize_key("plain-key_1.0") == "plain-key_1.0"


def test_clean_removes_expired_and_evicts_lru(tmp_path):
    cache = file_cache.FileCache(str(tmp_path / "c"), ttl=1000, max_size=10)
    now = time.time()
    for index, key in enumerate(["old", "a", "b", "c"]):
        cache.write(key, "12345")
        stamp = now - 5000 if key == "old" else now - 100 + index
        os.utime(cache.filename(key), (stamp, stamp))
    cache.clean()
    assert sorted(os.listdir(tmp_path / "c")) == ["b", "c"]


def test_invocation_cleans_cache(tmp_path):
    cache_root = tmp_path / "cache"
    cache = file_cache.FileCache(str(cache_root))
    cache.write("stale", "x")
    old = time.time() - file_cache.DEFAULT_TTL - 10
    os.utime(cache.filename("stale"), (old, old))
    cache.write("fresh", "x")
    call(tmp_path, "cli", "version", env={"APPCTL_CACHE_DIR": str(cache_root)})
    assert os.listdir(cache_root) == ["fresh"]


# --- archive extraction --------------------------------------------------------------

def make_archives(tmp_path):
    zpath = tmp_path / "pkg.zip"
    with zipfile.ZipFile(zpath, "w") as bundle:
        bundle.writestr("a.txt", "new a")
        bundle.writestr("sub/b.txt", "new b")
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("new a")
    (src / "sub" / "b.txt").write_text("new b")
    tpath = tmp_path / "pkg.tar.gz"
    with tarfile.open(tpath, "w:gz") as bundle:
        bundle.add(src / "a.txt", "a.txt")
        bundle.add(src / "sub", "sub")
    return zpath, tpath


@pytest.mark.parametrize("name", ["pkg.zip", "pkg.tar.gz"])
def test_extract_overwrites(tmp_path, name):
    make_archives(tmp_path)
    dest = tmp_path / "dest"
    (dest / "sub").mkdir(parents=True)
    (dest / "sub" / "b.txt").write_text("old")
    code, out, err = call(tmp_path, "cli", "update", f"--archive={name}", "--path=dest")
    assert code == 0, err
    assert out.startswith("Success: ")
    assert (dest / "a.txt").read_text() == "new a"
    assert (dest / "sub" / "b.txt").read_text() == "new b"


def test_extract_defaults_to_current_directory(tmp_path):
    make_archives(tmp_path)
    assert call(tmp_path, "cli", "update", "--archive=pkg.zip")[0] == 0
    assert (tmp_path / "a.txt").read_text() == "new a"


def test_strict_mode_accepts_path_after_command(tmp_path):
    make_archives(tmp_path)
    code, _, err = call(tmp_path, "cli", "update", "--archive=pkg.zip", "--path=d",
                        env={"APPCTL_STRICT_ARGS_MODE": "1"})
    assert code == 0, err
    assert (tmp_path / "d" / "a.txt").exists()


@pytest.mark.skipif(IS_ROOT, reason="root can write read-only files")
def test_non_writable_files_warn_then_fail(tmp_path):
    make_archives(tmp_path)
    dest = tmp_path / "dest"
    dest.mkdir()
    locked = dest / "a.txt"
    locked.write_text("keep")
    locked.chmod(0o444)
    code, _, err = call(tmp_path, "cli", "update", "--archive=pkg.zip", "--path=dest")
    assert code == 1
    assert err == ("Warning: Unable to copy 'a.txt' to current directory.\n"
                   "Error: There was an error overwriting existing files.\n")
    assert locked.read_text() == "keep"
    assert (dest / "sub" / "b.txt").read_text() == "new b"


def test_unsupported_format(tmp_path):
    prime_root(tmp_path / "root")
    (tmp_path / "pkg.rar").write_text("x")
    for name in ("pkg.rar", "pkg.tgz", "missing.7z"):
        code, out, err = call(tmp_path, "cli", "update", f"--archive={name}")
        assert (code, out) == (1, "")
        assert err == "Error: Extraction only supported for '.zip' and '.tar.gz' file types.\n"


def test_archive_is_validated(tmp_path):
    code, _, err = call(tmp_path, "cli", "update", "--archive=missing.zip", "--path=dest")
    assert code == 1 and err.startswith("Error: ") and not (tmp_path / "dest").exists()


def test_broken_tar_gz_warns_before_retry(tmp_path):
    (tmp_path / "bad.tar.gz").write_text("not an archive")
    code, _, err = call(tmp_path, "cli", "update", "--archive=bad.tar.gz", "--path=dest")
    lines = err.splitlines()
    assert code == 1
    assert lines[0].startswith("Warning: ") and "falling back" in lines[0]
    assert lines[-1].startswith("Error: ")


def test_script_extracts_archive(tmp_path):
    import subprocess
    make_archives(tmp_path)
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "appctl.py"), "cli", "update",
         "--archive=pkg.tar.gz", "--path=out"],
        cwd=tmp_path, capture_output=True, text=True,
        env=dict(os.environ, APPCTL_ROOT_DIR=str(tmp_path / "root")))
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "out" / "sub" / "b.txt").read_text() == "new b"
