"""End-to-end tests for ``signatures``, ``references``, ``search``, ``names``,
stub files and dynamic parameter inference."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

SITH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sith.py")

FILES = {
    "calc.py": '''\
        """Calc module."""


        class Calculator:
            """A calculator."""

            def __init__(self, start=0):
                self.value = start

            def add(self, a, b=1, *args, key: str = "k", **kw):
                """Add things."""
                return a + b

            def recalculate(self, x: int) -> int:
                local = x
                return local


        def compute(x):
            return x


        TOTAL = 10
        ''',
    "calc.pyi": '''\
        class Calculator:
            value: float
            def __init__(self, start: float = ...) -> None: ...
            def recalculate(self, x: int) -> int: ...
            def extra(self) -> str: ...

        def compute(x: int) -> str: ...
        TOTAL: int
        ONLY_STUB: bytes
        ''',
    "stubs/typed.pyi": '''\
        from typing import overload

        @overload
        def conv(x: int) -> str: ...
        @overload
        def conv(x: str) -> int: ...
        ''',
    "typed.py": '''\
        def conv(x):
            return x
        ''',
    "plain.py": '''\
        from dataclasses import dataclass


        def helper(a, b, /, c, *, d=4):
            """Help."""
            return a


        def run(cb, arg):
            return cb(arg)


        @dataclass
        class Point:
            x: int
            label: str = "p"


        x = 1
        x = 2
        print(x)
        run(helper, 5)
        helper("s", 1, 2)
        Point(1, label="q")


        def other():
            x = 3
            return x
        ''',
    "main.py": '''\
        from calc import Calculator, compute, ONLY_STUB
        import calc
        import typed

        c = Calculator()
        c.add(1, 2, key="x")
        r = compute(1)
        v = c.value
        e = c.extra()
        o = ONLY_STUB
        t = typed.conv(1)
        calc.TOTAL
        ''',
}


class FeatureTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = self.directory.name
        for name, text in FILES.items():
            path = os.path.join(self.root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write(textwrap.dedent(text))

    def tearDown(self):
        self.directory.cleanup()

    def run_sith(self, *args):
        result = subprocess.run([sys.executable, SITH] + [str(a) for a in args]
                                + ["--project", self.root],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def path(self, name):
        return os.path.join(self.root, name)

    def position(self, name, needle, offset=0):
        lines = textwrap.dedent(FILES[name]).split("\n")
        for number, text in enumerate(lines, 1):
            if needle in text:
                return number, text.index(needle) + offset
        raise AssertionError(needle)

    def signatures(self, name, needle, offset):
        line, col = self.position(name, needle, offset)
        return self.run_sith("signatures", self.path(name), line, col)["signatures"]

    def infer(self, name, needle, offset=0):
        line, col = self.position(name, needle, offset)
        return [d["name"] for d in
                self.run_sith("infer", self.path(name), line, col)["definitions"]]


class SignaturesTest(FeatureTestCase):
    def test_bound_method_and_index(self):
        [found] = self.signatures("main.py", "c.add(1, 2", 6)
        self.assertEqual(found, {
            "name": "add",
            "params": ["a", "b=1", "*args", "key: str=\"k\"", "**kw"],
            "index": 0,
            "description": "def add(a, b=1, *args, key: str=\"k\", **kw)",
            "docstring": "Add things."})
        indices = [self.signatures("main.py", "c.add(1, 2", offset)[0]["index"]
                   for offset in (8, 11, 18)]
        self.assertEqual(indices, [1, 2, 3])

    def test_not_in_call(self):
        self.assertEqual(self.signatures("main.py", "c.add(", 5), [])
        self.assertEqual(self.signatures("main.py", "c = Calculator()", 0), [])

    def test_binding_rules(self):
        def index(offset):
            return self.signatures("plain.py", 'helper("s", 1, 2)', offset)[0]["index"]
        self.assertEqual([index(7), index(12), index(15)], [0, 1, 2])
        [found] = self.signatures("plain.py", 'helper("s", 1, 2)', 7)
        self.assertEqual(found["description"], "def helper(a, b, /, c, *, d=4)")
        self.assertEqual(found["params"], ["a", "b", "c", "d=4"])
        [found] = self.signatures("plain.py", 'Point(1, label="q")', 11)
        self.assertEqual((found["name"], found["params"], found["index"]),
                         ("Point", ["x: int", 'label: str="p"'], 1))

    def test_unknown_keyword_and_extra_positional(self):
        source = "from plain import helper\nhelper(1, 2, 3, 4)\nhelper(1, e=3)\n"
        path = self.path("extra.py")
        with open(path, "w") as handle:
            handle.write(source)
        found = self.run_sith("signatures", path, 2, 16)["signatures"]
        self.assertIsNone(found[0]["index"])
        found = self.run_sith("signatures", path, 3, 12)["signatures"]
        self.assertIsNone(found[0]["index"])

    def test_stub_parameters_and_overloads(self):
        [found] = self.signatures("main.py", "c = Calculator()", 15)
        self.assertEqual((found["params"], found["description"], found["docstring"]),
                         (["start: float=..."], "def Calculator(start: float=...)",
                          "A calculator."))
        [found] = self.signatures("main.py", "r = compute(1)", 12)
        self.assertEqual(found["description"], "def compute(x: int) -> str")
        found = self.signatures("main.py", "t = typed.conv(1)", 15)
        self.assertEqual([s["description"] for s in found],
                         ["def conv(x: int) -> str", "def conv(x: str) -> int"])

    def test_through_dynamic_parameter(self):
        [found] = self.signatures("plain.py", "return cb(arg)", 10)
        self.assertEqual((found["name"], found["index"]), ("helper", 0))


class StubTest(FeatureTestCase):
    def test_infer_uses_stub_annotations(self):
        self.assertEqual(self.infer("main.py", "r = compute"), ["str"])
        self.assertEqual(self.infer("main.py", "v = c.value"), ["float"])
        self.assertEqual(self.infer("main.py", "e = c.extra"), ["str"])
        self.assertEqual(self.infer("main.py", "o = ONLY_STUB"), ["bytes"])
        self.assertEqual(self.infer("main.py", "t = typed"), ["str"])
        self.assertEqual(self.infer("main.py", "calc.TOTAL", 5), ["int"])

    def test_goto_prefers_source(self):
        line, col = self.position("main.py", "calc.TOTAL", 5)
        [found] = self.run_sith("goto", self.path("main.py"), line, col)["definitions"]
        self.assertEqual((found["module_path"], found["line"]), ("calc.py", 23))
        line, col = self.position("main.py", "e = c.extra", 6)
        [found] = self.run_sith("goto", self.path("main.py"), line, col)["definitions"]
        self.assertEqual((found["module_path"], found["line"]), ("calc.pyi", 5))

    def test_complete_includes_stub_members(self):
        path = self.path("main.py")
        with open(path, "a") as handle:
            handle.write("c.\n")
        line = len(textwrap.dedent(FILES["main.py"]).split("\n"))
        found = self.run_sith("complete", path, line, 2)["completions"]
        types = {c["name"]: c["description"] for c in found}
        self.assertEqual(types["value"], "instance of float")
        self.assertIn("extra", types)
        self.assertIn("add", types)


class DynamicInferenceTest(FeatureTestCase):
    def test_parameters_from_call_sites(self):
        self.assertEqual(self.infer("plain.py", "def helper(a", 11), ["str"])
        self.assertEqual(self.infer("plain.py", "def run(cb", 8), ["helper"])
        self.assertEqual(self.infer("calc.py", "local = x", 8), ["int"])


class ReferencesTest(FeatureTestCase):
    def references(self, name, needle, offset=0, *flags):
        line, col = self.position(name, needle, offset)
        found = self.run_sith("references", self.path(name), line, col, *flags)
        return [(r["module_path"], r["line"], r["column"], r["is_definition"])
                for r in found["references"]]

    def test_file_scope_and_rebinding(self):
        self.assertEqual(self.references("plain.py", "print(x)", 6), [
            ("plain.py", 19, 0, True), ("plain.py", 20, 0, True),
            ("plain.py", 21, 6, False)])

    def test_project_scope(self):
        self.assertEqual(self.references("main.py", "c = Calculator()", 4, "--scope", "project"), [
            ("calc.py", 4, 6, True), ("main.py", 1, 17, True), ("main.py", 5, 4, False)])
        self.assertEqual(self.references("main.py", "c = Calculator()", 4), [
            ("main.py", 1, 17, True), ("main.py", 5, 4, False)])

    def test_parameter_keyword(self):
        self.assertEqual(self.references("plain.py", "def helper(a, b, /, c, *, d", 26), [
            ("plain.py", 4, 26, True)])


class SearchAndNamesTest(FeatureTestCase):
    def test_search_ranking(self):
        found = self.run_sith("search", "calc")["definitions"]
        self.assertEqual([(d["name"], d["module_path"]) for d in found],
                         [("Calculator", "calc.py"), ("recalculate", "calc.py")])
        self.assertNotIn("docstring", found[0])
        found = self.run_sith("search", "X")["definitions"]
        self.assertEqual([(d["name"], d["line"]) for d in found],
                         [("x", 19), ("x", 20)])

    def test_search_skips_locals_and_imports(self):
        self.assertEqual(self.run_sith("search", "local")["definitions"], [])
        self.assertEqual(self.run_sith("search", "dataclass")["definitions"], [])

    def test_names(self):
        found = self.run_sith("names", self.path("plain.py"))["definitions"]
        self.assertEqual([(d["name"], d["line"]) for d in found],
                         [("dataclass", 1), ("helper", 4), ("run", 9), ("Point", 14),
                          ("x", 19), ("x", 20), ("other", 27)])
        self.assertTrue(all(d["is_definition"] for d in found))
        found = self.run_sith("names", self.path("plain.py"), "--all-scopes")["definitions"]
        names = [d["name"] for d in found]
        self.assertTrue({"a", "cb", "label", "x"} <= set(names))
        self.assertEqual(names.count("x"), 4)


if __name__ == "__main__":
    unittest.main()
