"""End-to-end tests for `sith.py complete`."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

SITH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sith.py")


def dedent(source):
    """Like textwrap.dedent, but keeps the indentation of whitespace-only lines."""
    lines = source.split("\n")
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    margin = min(indents) if indents else 0
    return "\n".join(l[min(margin, len(l) - len(l.lstrip())):] for l in lines)


class SithTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, source):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(dedent(source))
        return path

    def run_sith(self, *args):
        return subprocess.run([sys.executable, SITH, "complete", *map(str, args)],
                              capture_output=True, text=True)

    def complete(self, source, line, col, *flags, name="main.py"):
        path = self.write(name, source)
        result = self.run_sith(path, line, col, *flags)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.endswith("\n"))
        self.assertNotIn(" ", result.stdout.split('"description"')[0].replace('" ', ""))
        return json.loads(result.stdout)["completions"]

    @staticmethod
    def by_name(completions):
        return {c["name"]: c for c in completions}

    @staticmethod
    def names(completions, include_keywords=True):
        return [c["name"] for c in completions if include_keywords or c["type"] != "keyword"]


class NameCompletionTests(SithTestCase):
    def test_builtin_prefix(self):
        result = self.by_name(self.complete("pr", 1, 2))
        self.assertEqual(result["print"], {"name": "print", "complete": "int", "type": "function",
                                           "description": "def print(...)"})
        self.assertEqual(result["property"]["description"], "class property")
        self.assertEqual(result["property"]["complete"], "operty")

    def test_case_insensitive_complete_by_length(self):
        result = self.by_name(self.complete("PRI", 1, 3))
        self.assertEqual(result["print"]["complete"], "nt")

    def test_scopes_and_visibility(self):
        source = "\n".join([
            "import os",
            "GLOBAL = 1",
            "def outer(p, q=3):",
            "    local = [1]",
            "    def inner():",
            "        z = 1",
            "        ",
            "    return inner",
            "LATER = 2",
        ])
        result = self.by_name(self.complete(source, 7, 8))
        for name in ("z", "local", "p", "q", "inner", "outer", "GLOBAL", "os", "print"):
            self.assertIn(name, result)
        self.assertNotIn("LATER", result)
        self.assertEqual(result["p"]["type"], "param")
        self.assertEqual(result["os"]["description"], "module os")
        self.assertEqual(result["local"]["description"], "instance of list")

    def test_not_visible_before_definition(self):
        source = "a = 1\n\nb = 2\n"
        names = self.names(self.complete(source, 2, 0))
        self.assertIn("a", names)
        self.assertNotIn("b", names)

    def test_ordering(self):
        source = "_priv = 1\n__dund__ = 2\nZeta = 3\nalpha = 4\n\n"
        completions = self.complete(source, 5, 0)
        names = self.names(completions)
        self.assertLess(names.index("alpha"), names.index("Zeta"))
        self.assertLess(names.index("Zeta"), names.index("_priv"))
        self.assertLess(names.index("_priv"), names.index("__dund__"))
        first_keyword = next(i for i, c in enumerate(completions) if c["type"] == "keyword")
        self.assertTrue(all(c["type"] == "keyword" for c in completions[first_keyword:]))
        keywords = names[first_keyword:]
        self.assertEqual(keywords, sorted(keywords, key=str.lower))

    def test_keywords_included(self):
        result = self.by_name(self.complete("wh", 1, 2))
        self.assertEqual(result["while"], {"name": "while", "complete": "ile", "type": "keyword",
                                           "description": "while"})

    def test_fuzzy(self):
        names = self.names(self.complete("isins", 1, 5))
        self.assertIn("isinstance", names)
        names = self.names(self.complete("isnc", 1, 4, "--fuzzy"))
        self.assertIn("isinstance", names)
        completion = self.by_name(self.complete("isnc", 1, 4, "--fuzzy"))["isinstance"]
        self.assertEqual(completion["complete"], "stance")

    def test_star_import_local_module(self):
        self.write("helper.py", "def helper_fn(): pass\nVALUE = 3\n_hidden = 1\n")
        result = self.by_name(self.complete("from helper import *\n", 2, 0))
        self.assertEqual(result["helper_fn"]["type"], "function")
        self.assertEqual(result["VALUE"]["description"], "instance of int")
        self.assertNotIn("_hidden", result)

    def test_star_import_installed(self):
        result = self.by_name(self.complete("from os import *\ngetc", 2, 4))
        self.assertIn("getcwd", result)

    def test_from_import_types(self):
        source = "from os.path import join\nfrom os import path\nfrom collections import OrderedDict\n"
        result = self.by_name(self.complete(source, 4, 0))
        self.assertEqual(result["join"]["type"], "function")
        self.assertEqual(result["path"]["type"], "module")
        self.assertEqual(result["OrderedDict"]["type"], "class")

    def test_class_body_scope(self):
        source = "class A:\n    x = 1\n    \n"
        self.assertIn("x", self.names(self.complete(source, 3, 4)))
        source = "class A:\n    x = 1\n    def m(self):\n        \n"
        names = self.names(self.complete(source, 4, 8))
        self.assertNotIn("x", names)
        self.assertIn("self", names)


class AttributeCompletionTests(SithTestCase):
    SOURCE = """\
        import os
        class Base:
            attr = []
            def base_method(self):
                pass

        class Child(Base):
            def __init__(self, x):
                self.x = x
                self.items = {}

            def method(self):
                return Child(1)

        c = Child(2)
        """

    def test_instance(self):
        source = self.SOURCE + "c.\n"
        result = self.by_name(self.complete(source, 16, 2))
        self.assertEqual(set(result), {"attr", "base_method", "method", "x", "items", "__init__"})
        self.assertEqual(result["items"]["description"], "instance of dict")
        self.assertTrue(all(c["type"] != "keyword" for c in result.values()))

    def test_class(self):
        source = self.SOURCE + "Child.\n"
        names = self.names(self.complete(source, 16, 6))
        self.assertEqual(names, ["attr", "base_method", "method", "__init__"])

    def test_method_return(self):
        source = self.SOURCE + "c.method().ite\n"
        self.assertEqual(self.names(self.complete(source, 16, 14)), ["items"])

    def test_self(self):
        source = "class A:\n    def __init__(self):\n        self.v = 1\n    def m(self):\n        self.\n"
        self.assertEqual(self.names(self.complete(source, 5, 13)), ["m", "v", "__init__"])

    def test_module(self):
        source = self.SOURCE + "os.pat\n"
        names = self.names(self.complete(source, 16, 6))
        self.assertIn("path", names)
        self.assertTrue(all(not n.startswith("_") for n in self.names(
            self.complete(self.SOURCE + "os.\n", 16, 3))))

    def test_literals(self):
        self.assertIn("upper", self.names(self.complete('"abc".up', 1, 8)))
        self.assertIn("append", self.names(self.complete("[1, 2].", 1, 7)))
        self.assertIn("keys", self.names(self.complete("{}.", 1, 3)))
        self.assertIn("add", self.names(self.complete("{1}.", 1, 4)))

    def test_unknown_receiver(self):
        self.assertEqual(self.complete("unknown_thing.", 1, 14), [])


class ToleranceAndErrorTests(SithTestCase):
    def test_syntax_errors(self):
        source = """\
            import os
            def broken(:
                pass
            value = 1
            def f():
                print(os.path.join(
            va
            """
        self.assertIn("value", self.names(self.complete(source, 7, 2)))

    def test_incomplete_block_at_eof(self):
        source = "def f(arg):\n    "
        self.assertIn("arg", self.names(self.complete(source, 2, 4)))

    def test_position_errors(self):
        path = self.write("main.py", "x = 1\n")
        self.assertEqual(self.run_sith(path, 10, 0).returncode, 1)
        self.assertEqual(self.run_sith(path, 1, 6).returncode, 1)
        self.assertEqual(self.run_sith(path, 0, 0).returncode, 1)
        self.assertEqual(self.run_sith(path, 1, 5).returncode, 0)

    def test_file_errors(self):
        result = self.run_sith(os.path.join(self.dir, "missing.py"), 1, 0)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr)
        self.assertEqual(self.run_sith(self.dir, 1, 0).returncode, 1)
        bad = os.path.join(self.dir, "bad.py")
        with open(bad, "wb") as handle:
            handle.write(b"\xff\xfe\x00")
        self.assertEqual(self.run_sith(bad, 1, 0).returncode, 1)

    def test_zero_completions_exit_zero(self):
        self.assertEqual(self.complete("zzzzqqq", 1, 7), [])


if __name__ == "__main__":
    unittest.main()
