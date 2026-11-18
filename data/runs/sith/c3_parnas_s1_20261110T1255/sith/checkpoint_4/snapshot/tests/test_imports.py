"""End-to-end tests for cross-file imports (``goto``/``infer``/``complete``)."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

SITH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sith.py")

FILES = {
    "helpers.py": '''\
        """Helpers."""
        import os

        __all__ = ["Helper", "make"]


        class Helper:
            """A helper."""

            def run(self):
                return 1


        def make():
            return Helper()


        def _private():
            pass


        VALUE = 3
        ''',
    "pkg/__init__.py": '''\
        from .core import Engine
        ''',
    "pkg/core.py": '''\
        class Engine:
            def start(self):
                return "ok"


        def build():
            return Engine()
        ''',
    "pkg/sub/__init__.py": "",
    "pkg/sub/deep.py": '''\
        from ..core import build as make_engine
        from ...outside import nothing
        ''',
    "ns/inner/mod.py": '''\
        def nsfunc():
            return []
        ''',
    "reexport.py": '''\
        from helpers import make as mk
        from os import getcwd
        ''',
    "a.py": '''\
        from b import *
        A_VAL = 1
        ''',
    "b.py": '''\
        from a import *
        B_VAL = "s"
        ''',
    "broken.py": '''\
        class Good:
            pass

        def bad(:
            pass
        ''',
    "main.py": '''\
        import helpers
        from helpers import Helper
        from reexport import mk, getcwd
        from pkg.sub.deep import make_engine, nothing
        from ns.inner.mod import nsfunc
        from helpers import *
        from a import *
        from broken import Good
        import requests

        h = Helper()
        x = mk()
        e = make_engine()
        w = nsfunc()
        helpers.make
        getcwd
        VALUE
        B_VAL
        Good
        requests
        ''',
}


class ImportTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = self.directory.name
        for name, text in FILES.items():
            self.write(name, text)

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name, text):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(textwrap.dedent(text))
        return path

    def run_sith(self, *args):
        result = subprocess.run([sys.executable, SITH] + [str(a) for a in args],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def main_position(self, needle, name):
        lines = textwrap.dedent(FILES["main.py"]).split("\n")
        for number, text in enumerate(lines, 1):
            if text.startswith(needle):
                return number, text.index(name)
        raise AssertionError(needle)

    def goto(self, needle, name, *flags):
        line, col = self.main_position(needle, name)
        return self.run_sith("goto", os.path.join(self.root, "main.py"), line, col,
                             *flags)["definitions"]

    def infer(self, needle, name):
        line, col = self.main_position(needle, name)
        return self.run_sith("infer", os.path.join(self.root, "main.py"), line,
                             col)["definitions"]

    def complete(self, source, *flags):
        path = self.write("main.py", source)
        lines = textwrap.dedent(source).split("\n")
        line = len(lines) - 1 if lines[-1] == "" else len(lines)
        completions = self.run_sith("complete", path, line, len(lines[line - 1]), *flags)
        return [c["name"] for c in completions["completions"]]


class GotoTest(ImportTestCase):
    def test_default_returns_import_statement(self):
        [found] = self.goto("h = Helper()", "Helper")
        self.assertEqual((found["module_path"], found["line"], found["column"],
                          found["description"]),
                         ("main.py", 2, 20, "from helpers import Helper"))

    def test_follow_imports(self):
        [found] = self.goto("h = Helper()", "Helper", "--follow-imports")
        self.assertEqual((found["name"], found["type"], found["full_name"],
                          found["module_path"], found["line"], found["column"]),
                         ("Helper", "class", "helpers.Helper", "helpers.py", 7, 6))

    def test_follow_chain_and_relative_imports(self):
        [found] = self.goto("x = mk()", "mk", "--follow-imports")
        self.assertEqual((found["module_path"], found["line"]), ("helpers.py", 14))
        [found] = self.goto("e = make_engine()", "make_engine", "--follow-imports")
        self.assertEqual((found["full_name"], found["module_path"]),
                         ("pkg.core.build", "pkg/core.py"))
        [found] = self.goto("w = nsfunc()", "nsfunc", "--follow-imports")
        self.assertEqual(found["module_path"], "ns/inner/mod.py")

    def test_follow_module(self):
        [found] = self.goto("helpers.make", "helpers", "--follow-imports")
        self.assertEqual((found["type"], found["module_path"], found["line"]),
                         ("module", "helpers.py", 1))

    def test_unresolvable_falls_back_to_import(self):
        for needle, name, line in (("getcwd", "getcwd", 3), ("requests", "requests", 9)):
            [found] = self.goto(needle, name, "--follow-imports")
            self.assertEqual((found["module_path"], found["line"]), ("main.py", line))


class InferTest(ImportTestCase):
    def test_across_files(self):
        [found] = self.infer("h = Helper()", "h")
        self.assertEqual((found["type"], found["full_name"], found["module_path"],
                          found["docstring"]),
                         ("instance", "helpers.Helper", "helpers.py", "A helper."))
        self.assertEqual([d["full_name"] for d in self.infer("x = mk()", "x")],
                         ["helpers.Helper"])
        self.assertEqual([d["full_name"] for d in self.infer("e = make_engine", "e")],
                         ["pkg.core.Engine"])

    def test_star_import_respects_all(self):
        self.assertEqual(self.infer("VALUE", "VALUE"), [])

    def test_circular_star_imports(self):
        self.assertEqual([d["name"] for d in self.infer("B_VAL", "B_VAL")], ["str"])

    def test_syntax_error_and_missing_module(self):
        self.assertEqual([d["name"] for d in self.infer("Good", "Good")], ["Good"])
        self.assertEqual(self.infer("requests", "requests"), [])

    def test_relative_import_above_root(self):
        path = os.path.join(self.root, "pkg", "sub", "deep.py")
        result = self.run_sith("infer", path, 2, 23, "--project", self.root)
        self.assertEqual(result["definitions"], [])


class CompleteTest(ImportTestCase):
    def test_import_module_names(self):
        self.assertEqual(self.complete("import hel"), ["helpers"])
        self.assertEqual(self.complete("import pkg."), ["core", "sub"])
        self.assertEqual(self.complete("import pkg.sub.d"), ["deep"])
        self.assertIn("ns", self.complete("import "))
        self.assertEqual(self.complete("from ns.inner import "), ["mod"])

    def test_from_import_names(self):
        self.assertEqual(self.complete("from helpers import "), ["Helper", "make"])
        self.assertEqual(self.complete("from pkg import "), ["core", "Engine", "sub"])
        self.assertEqual(self.complete("from pkg.core import E"), ["Engine"])
        self.assertEqual(self.complete("from reexport import (mk,\n    "),
                         ["getcwd", "mk"])
        self.assertEqual(self.complete("from requests import "), [])

    def test_attribute_of_imported_module(self):
        source = "import helpers\nhelpers.make().r"
        self.assertEqual(self.complete(source), ["run"])
        self.assertIn("VALUE", self.complete("import helpers\nhelpers."))


if __name__ == "__main__":
    unittest.main()
