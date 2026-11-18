"""End-to-end tests for ``sith.py rename`` / ``inline`` / ``extract-variable`` /
``extract-function`` / ``errors``."""

import ast
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

SITH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sith.py")


class RefactoringTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = self.directory.name

    def tearDown(self):
        self.directory.cleanup()

    def write(self, relative, text):
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(textwrap.dedent(text))
        return path

    def run_sith(self, *args):
        return subprocess.run([sys.executable, SITH] + [str(a) for a in args],
                              capture_output=True, text=True, cwd=self.root)

    def changes(self, *args):
        result = self.run_sith(*args, "--project", self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_fails(self, *args):
        result = self.run_sith(*args, "--project", self.root)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        return result.stderr


class RenameTest(RefactoringTestCase):
    def setUp(self):
        RefactoringTestCase.setUp(self)
        self.utils = self.write("utils.py", """\
            def helper(x):
                return x + 1

            LIMIT = 3
            """)
        self.main = self.write("main.py", """\
            import utils
            from utils import helper, LIMIT


            def run():
                value = helper(LIMIT)
                return utils.helper(value)
            """)

    def test_function_across_files(self):
        out = self.changes("rename", self.main, 6, 12, "--new-name", "assist")
        self.assertEqual(out["renames"], {})
        self.assertEqual(sorted(out["changed_files"]), ["main.py", "utils.py"])
        self.assertIn("def assist(x):", out["changed_files"]["utils.py"])
        main = out["changed_files"]["main.py"]
        self.assertIn("from utils import assist, LIMIT", main)
        self.assertIn("value = assist(LIMIT)", main)
        self.assertIn("utils.assist(value)", main)

    def test_local_only_changes_one_file(self):
        out = self.changes("rename", self.main, 6, 4, "--new-name", "result")
        self.assertEqual(list(out["changed_files"]), ["main.py"])
        self.assertIn("return utils.helper(result)", out["changed_files"]["main.py"])

    def test_module_rename(self):
        out = self.changes("rename", self.main, 1, 8, "--new-name", "tools")
        self.assertEqual(out["renames"], {"utils.py": "tools.py"})
        main = out["changed_files"]["main.py"]
        self.assertTrue(main.startswith("import tools\nfrom tools import helper, LIMIT\n"))
        self.assertIn("tools.helper(value)", main)
        self.assertNotIn("utils.py", out["changed_files"])

    def test_package_rename(self):
        self.write("pkg/__init__.py", "")
        self.write("pkg/sub.py", "def f():\n    return 1\n")
        user = self.write("user.py", "import pkg.sub\nfrom pkg import sub\nprint(pkg.sub.f())\n")
        out = self.changes("rename", user, 1, 8, "--new-name", "lib")
        self.assertEqual(out["renames"], {"pkg": "lib"})
        self.assertEqual(out["changed_files"]["user.py"],
                         "import lib.sub\nfrom lib import sub\nprint(lib.sub.f())\n")

    def test_diff(self):
        result = self.run_sith("rename", self.utils, 1, 4, "--new-name", "assist", "--diff",
                               "--project", self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--- utils.py\n+++ utils.py\n", result.stdout)
        self.assertIn("-def helper(x):\n+def assist(x):\n", result.stdout)
        self.assertIn("+from utils import assist, LIMIT\n", result.stdout)

    def test_invalid_name(self):
        self.assert_fails("rename", self.main, 6, 12, "--new-name", "2bad")
        self.assert_fails("rename", self.main, 6, 12, "--new-name", "class")

    def test_not_on_name(self):
        self.assert_fails("rename", self.main, 3, 0, "--new-name", "other")

    def test_collision(self):
        message = self.assert_fails("rename", self.main, 6, 12, "--new-name", "LIMIT")
        self.assertIn("LIMIT", message)


class InlineTest(RefactoringTestCase):
    def test_parentheses_only_when_needed(self):
        path = self.write("calc.py", """\
            def calc(a, b, c):
                x = a + b
                y = x * c
                z = c - x
                return print(x, y, z)
            """)
        out = self.changes("inline", path, 2, 4)
        self.assertEqual(out["changed_files"]["calc.py"], textwrap.dedent("""\
            def calc(a, b, c):
                y = (a + b) * c
                z = c - (a + b)
                return print(a + b, y, z)
            """))

    def test_from_reference(self):
        path = self.write("one.py", "n = -2\nprint(n ** 2)\n")
        out = self.changes("inline", path, 2, 6)
        self.assertEqual(out["changed_files"]["one.py"], "print((-2) ** 2)\n")

    def test_refusals(self):
        path = self.write("two.py", "def f():\n    return 1\n\nunused = 3\nf()\n")
        self.assertIn("cannot inline a function/class definition",
                      self.assert_fails("inline", path, 1, 4))
        self.assertIn("name has no references to inline",
                      self.assert_fails("inline", path, 4, 0))


class ExtractVariableTest(RefactoringTestCase):
    def test_extract(self):
        path = self.write("area.py", """\
            def area(w, h):
                return compute(w * h, 2) + 1
            """)
        out = self.changes("extract-variable", path, 2, 19, "--until", "2:24", "--name", "size")
        self.assertEqual(out["changed_files"]["area.py"], textwrap.dedent("""\
            def area(w, h):
                size = w * h
                return compute(size, 2) + 1
            """))

    def test_partial_selection(self):
        path = self.write("area.py", "result = compute(w * h, 2) + 1\n")
        self.assertIn("selection is not a complete expression",
                      self.assert_fails("extract-variable", path, 1, 9, "--until", "1:20",
                                        "--name", "part"))

    def test_invalid_name(self):
        path = self.write("area.py", "result = a + b\n")
        self.assert_fails("extract-variable", path, 1, 9, "--until", "1:14", "--name", "a-b")


class ExtractFunctionTest(RefactoringTestCase):
    def test_module_level_parameters_and_return(self):
        path = self.write("mod.py", """\
            x = 10
            y = 20
            z = x + y
            print(z)
            """)
        out = self.changes("extract-function", path, 3, 0, "--until", "3:9", "--name", "add")
        new = out["changed_files"]["mod.py"]
        self.assertTrue(new.startswith("x = 10\ny = 20\ndef add(x, y):\n    z = x + y\n"
                                       "    return z\n"))
        self.assertIn("\nz = add(x, y)\nprint(z)\n", new)
        ast.parse(new)

    def test_function_level_tuple_return(self):
        path = self.write("proc.py", """\
            def process(items, factor):
                total = 0
                count = 0
                for item in items:
                    total += item * factor
                    count += 1
                return total / count, count
            """)
        out = self.changes("extract-function", path, 4, 0, "--until", "6:18",
                           "--name", "loop")
        new = out["changed_files"]["proc.py"]
        self.assertTrue(new.startswith("def loop(items, total, factor, count):\n"))
        self.assertIn("    return total, count\n\n\ndef process(items, factor):", new)
        self.assertIn("    total, count = loop(items, total, factor, count)\n", new)
        namespace = {}
        exec(new, namespace)
        self.assertEqual(namespace["process"]([1, 2, 3], 2), (4.0, 3))

    def test_partial_statement(self):
        path = self.write("mod.py", "x = 1\ny = x + 2\n")
        self.assert_fails("extract-function", path, 2, 4, "--until", "2:9", "--name", "f")


class ErrorsTest(RefactoringTestCase):
    def test_clean_file(self):
        path = self.write("ok.py", "x = 1\n")
        result = self.run_sith("errors", path)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {"errors": []})

    def test_errors(self):
        path = self.write("bad.py", "x = 1\nif True\n    y = 2\nfoo bar\n")
        result = self.run_sith("errors", path)
        self.assertEqual(result.returncode, 0)
        errors = json.loads(result.stdout)["errors"]
        self.assertEqual([e["line"] for e in errors], [2, 4])
        for error in errors:
            self.assertEqual(sorted(error), ["column", "line", "message", "until_column",
                                             "until_line"])
            self.assertTrue(error["message"])

    def test_missing_file(self):
        self.assertEqual(self.run_sith("errors", "missing.py").returncode, 1)


if __name__ == "__main__":
    unittest.main()
