"""External command execution, the file cache and archive extraction."""

import io
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import zipfile

from appctl_cli.file_cache import FileCache, cache_dir, sanitize_key
from appctl_cli.output import Output
from appctl_cli.process import exec_command, run_command, runtime_flags, self_command

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "appctl.py")


def debug_output():
    stderr = io.StringIO()
    return Output(debug=True, stdout=io.StringIO(), stderr=stderr), stderr


class ProcessTest(unittest.TestCase):
    def test_detailed_result_and_debug_log(self):
        output, stderr = debug_output()
        result = run_command("echo out; echo err >&2; exit 3", output)
        self.assertEqual((result.stdout, result.stderr, result.return_code), ("out\n", "err\n", 3))
        self.assertGreaterEqual(result.run_time, 0)
        lines = stderr.getvalue().splitlines()
        self.assertTrue(lines[0].startswith("Debug: COMMAND: echo out"))
        self.assertTrue(lines[1].startswith("Debug: STDOUT: out"))
        self.assertTrue(lines[2].startswith("Debug: STDERR: err"))
        self.assertTrue(lines[3].startswith("Debug: RETURN CODE: 3"))

    def test_success_only(self):
        output, stderr = debug_output()
        self.assertTrue(exec_command(["true"], output))
        self.assertFalse(exec_command("false", output))
        self.assertIn("Debug: COMMAND: true", stderr.getvalue())

    def test_obfuscation(self):
        output, stderr = debug_output()
        result = run_command("echo s3cret", output, obfuscate_list=["s3cret"])
        self.assertEqual(result.stdout, "s3cret\n")
        self.assertNotIn("s3cret", stderr.getvalue())
        self.assertIn("COMMAND: echo ******", stderr.getvalue())

    def test_exit_code_minus_one_warns(self):
        output, stderr = debug_output()
        self.assertEqual(run_command("kill -HUP $$", output).return_code, -1)
        self.assertIn("Warning: Spawned process returned exit code -1", stderr.getvalue())
        self.assertIn("signal handling configuration", stderr.getvalue())

    def test_self_command_preserves_runtime_flags(self):
        runtime = {"debug": True, "color": False, "url": "u", "quiet": False, "context": "cli"}
        self.assertEqual(runtime_flags(runtime), ["--url=u", "--no-color", "--debug"])
        self.assertEqual(self_command("cli info", runtime=runtime)[-2:], ["cli", "info"])


class FileCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.cache = FileCache(os.path.join(self.tmp, "cache"), ttl=100, max_size=10)

    def test_location(self):
        self.assertEqual(cache_dir({"APPCTL_CACHE_DIR": "/c", "APPCTL_ROOT_DIR": "/r"}), "/c")
        self.assertEqual(cache_dir({"APPCTL_ROOT_DIR": "/r"}), "/r/.cache/")

    def test_read_write_and_expiry(self):
        self.assertFalse(self.cache.read("k"))
        self.assertTrue(self.cache.write("k", "hello"))
        self.assertEqual(self.cache.read("k"), "hello")
        path = self.cache.has("k")
        os.utime(path, (time.time() - 200, time.time() - 200))
        self.assertFalse(self.cache.read("k"))
        self.assertFalse(os.path.exists(path))

    def test_clean_evicts_least_recently_used(self):
        for index, key in enumerate("abc"):
            self.cache.write(key, "xxxx")
            os.utime(self.cache.filename(key), (time.time() - 10 + index,) * 2)
        self.cache.clean()
        self.assertEqual([k for k in "abc" if self.cache.has(k)], ["b", "c"])

    def test_creation_failure_disables_cache(self):
        blocker = os.path.join(self.tmp, "file")
        open(blocker, "w").close()
        output, stderr = debug_output()
        cache = FileCache(os.path.join(blocker, "c"), output=output)
        self.assertFalse(cache.is_enabled())
        self.assertFalse(cache.write("k", "v"))
        self.assertIn(f"Warning: Failed to create directory '{blocker}/c': ", stderr.getvalue())

    def test_sanitize_key(self):
        self.assertEqual(sanitize_key("core/file-1.0.zip"), "core/file-1.0.zip")
        self.assertEqual(sanitize_key("a b"), sanitize_key("a b"))
        self.assertNotEqual(sanitize_key("a b"), sanitize_key("a-b"))
        self.assertNotIn("..", sanitize_key("../../etc/passwd").split("/"))
        self.assertTrue(sanitize_key("https://x.test/a.zip").startswith("misc/https-x.test/"))


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("APPCTL_")}
        self.env["APPCTL_ROOT_DIR"] = os.path.join(self.tmp, "root")
        self.dest = os.path.join(self.tmp, "dest")

    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                              env=self.env, cwd=self.tmp)

    def make_zip(self):
        path = os.path.join(self.tmp, "a.zip")
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("one.txt", "1")
            bundle.writestr("sub/two.txt", "2")
        return path

    def test_zip(self):
        result = self.run_cli("cli", "update", f"--archive={self.make_zip()}", f"--path={self.dest}")
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(os.path.join(self.dest, "sub", "two.txt")) as handle:
            self.assertEqual(handle.read(), "2")

    def test_tarball(self):
        source = os.path.join(self.tmp, "x.txt")
        with open(source, "w") as handle:
            handle.write("x")
        path = os.path.join(self.tmp, "a.tar.gz")
        with tarfile.open(path, "w:gz") as bundle:
            bundle.add(source, "x.txt")
        result = self.run_cli("cli", "update", f"--archive={path}", f"--path={self.dest}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.dest, "x.txt")))

    def test_broken_tarball_warns_before_retry(self):
        path = os.path.join(self.tmp, "bad.tar.gz")
        with open(path, "w") as handle:
            handle.write("junk")
        result = self.run_cli("cli", "update", f"--archive={path}", f"--path={self.dest}")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.startswith("Warning: "))

    def test_unsupported(self):
        result = self.run_cli("cli", "update", "--archive=a.rar")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr,
                         "Error: Extraction only supported for '.zip' and '.tar.gz' file types.\n")

    def test_non_writable_files(self):
        archive = self.make_zip()
        os.makedirs(os.path.join(self.dest, "sub"))
        for name in ("one.txt", "sub/two.txt"):
            with open(os.path.join(self.dest, name), "w") as handle:
                handle.write("old")
        locked = os.path.join(self.dest, "sub", "two.txt")
        os.chmod(locked, stat.S_IRUSR)
        self.addCleanup(os.chmod, locked, stat.S_IRUSR | stat.S_IWUSR)
        result = self.run_cli("cli", "update", f"--archive={archive}", f"--path={self.dest}")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Warning: Unable to copy 'sub/two.txt' to current directory.\n", result.stderr)
        with open(os.path.join(self.dest, "one.txt")) as handle:
            self.assertEqual(handle.read(), "1")


if __name__ == "__main__":
    unittest.main()
