"""End-to-end tests for ``sith.py infer`` / ``goto`` / ``complete``."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

SITH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sith.py")

EXAMPLE = '''\
import os
from dataclasses import dataclass
from typing import Optional


class Calculator:
    """A calculator."""

    def __init__(self, start=0):
        self.value = start

    def add(self, a, b):
        return a + b

    def maybe(self, flag):
        if flag:
            return 1
        return "one"

    def nothing(self):
        pass


@dataclass(frozen=True)
class Point:
    x: int
    label: str = "p"


calc = Calculator()
total = calc.add(1, 2)
m = calc.maybe(True)
z = calc.nothing()
p = Point(1)
v = calc.value
num = 42
if num > 3:
    cond = 1
else:
    cond = "s"
cond


def narrow(obj, opt: Optional[Calculator] = None):
    if isinstance(obj, Calculator):
        obj
    obj
    if opt is None:
        return
    opt
'''


class SithTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "example.py")
        with open(self.path, "w") as handle:
            handle.write(EXAMPLE)
        self.lines = EXAMPLE.split("\n")

    def tearDown(self):
        self.directory.cleanup()

    def run_sith(self, *args):
        return subprocess.run([sys.executable, SITH] + [str(a) for a in args],
                              capture_output=True, text=True)

    def position(self, needle, name, occurrence=0):
        for number, text in enumerate(self.lines, 1):
            if needle in text:
                col = -1
                for _ in range(occurrence + 1):
                    col = text.index(name, col + 1)
                return number, col
        raise AssertionError("needle not found: %r" % needle)

    def definitions(self, command, needle, name, occurrence=0):
        line, col = self.position(needle, name, occurrence)
        result = self.run_sith(command, self.path, line, col)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["definitions"]

    def names(self, command, needle, name, occurrence=0):
        return [(d["name"], d["type"])
                for d in self.definitions(command, needle, name, occurrence)]


class InferTest(SithTestCase):
    def test_instance_of_class(self):
        [found] = self.definitions("infer", "calc = Calculator()", "calc")
        self.assertEqual(found, {
            "name": "Calculator", "type": "instance", "full_name": "example.Calculator",
            "module_path": "example.py", "line": 6, "column": 6,
            "description": "instance of Calculator", "docstring": "A calculator."})

    def test_literal_and_call_arguments(self):
        [found] = self.definitions("infer", "num = 42", "num")
        self.assertEqual((found["full_name"], found["module_path"], found["line"],
                          found["column"]), ("builtins.int", "", 0, 0))
        self.assertEqual(self.names("infer", "total = calc", "total"), [("int", "instance")])

    def test_union_and_none_returns(self):
        self.assertEqual(self.names("infer", "m = calc", "m"),
                         [("int", "instance"), ("str", "instance")])
        self.assertEqual(self.names("infer", "z = calc", "z"), [("None", "instance")])

    def test_attributes_and_dataclass_fields(self):
        self.assertEqual(self.names("infer", "v = calc.value", "v"), [("int", "instance")])
        self.assertEqual(self.names("infer", "p = Point(1)", "p"), [("Point", "instance")])

    def test_conditional_assignment(self):
        self.assertEqual(self.names("infer", "cond", "cond", 0)[0], ("int", "instance"))
        line = self.lines.index("cond") + 1
        result = json.loads(self.run_sith("infer", self.path, line, 0).stdout)
        self.assertEqual([d["name"] for d in result["definitions"]], ["int", "str"])

    def test_narrowing(self):
        line = self.lines.index("        obj") + 1
        result = json.loads(self.run_sith("infer", self.path, line, 8).stdout)
        self.assertEqual([d["name"] for d in result["definitions"]], ["Calculator"])
        line = self.lines.index("    obj") + 1
        result = json.loads(self.run_sith("infer", self.path, line, 4).stdout)
        self.assertEqual(result["definitions"], [])
        line = self.lines.index("    opt") + 1
        result = json.loads(self.run_sith("infer", self.path, line, 4).stdout)
        self.assertEqual([d["name"] for d in result["definitions"]], ["Calculator"])

    def test_function_name(self):
        [found] = self.definitions("infer", "total = calc.add", "add")
        self.assertEqual((found["type"], found["full_name"], found["description"]),
                         ("function", "example.Calculator.add", "def add(self, a, b)"))

    def test_not_on_name(self):
        line, _ = self.position("num = 42", "num")
        self.assertEqual(self.run_sith("infer", self.path, line, 7).returncode, 1)
        self.assertEqual(self.run_sith("goto", self.path, line, 7).returncode, 1)


class GotoTest(SithTestCase):
    def test_assignment_and_branches(self):
        [found] = self.definitions("goto", "total = calc", "calc")
        self.assertEqual((found["name"], found["type"], found["line"], found["column"]),
                         ("calc", "statement", 30, 0))
        line = self.lines.index("cond") + 1
        result = json.loads(self.run_sith("goto", self.path, line, 0).stdout)
        self.assertEqual([(d["line"], d["column"]) for d in result["definitions"]],
                         [(38, 4), (40, 4)])

    def test_import_and_class(self):
        [found] = self.definitions("goto", "    opt", "opt")
        self.assertEqual(found["type"], "param")
        [found] = self.definitions("goto", "calc = Calculator()", "Calculator")
        self.assertEqual((found["type"], found["line"], found["column"]), ("class", 6, 6))
        [found] = self.definitions("goto", "class Point", "Point")
        self.assertEqual(found["description"], "class Point")

    def test_unresolved(self):
        with open(self.path, "a") as handle:
            handle.write("missing_name\n")
        line = len(self.lines)
        result = self.run_sith("goto", self.path, line, 0)
        self.assertEqual((result.returncode, json.loads(result.stdout)["definitions"]),
                         (0, []))


class CompleteTest(SithTestCase):
    def complete(self, source, line, col):
        with open(self.path, "w") as handle:
            handle.write(textwrap.dedent(source))
        result = self.run_sith("complete", self.path, line, col)
        return [c["name"] for c in json.loads(result.stdout)["completions"]]

    def test_union_and_narrowing(self):
        source = '''\
        class A:
            def a_method(self): pass
        class B:
            def b_method(self): pass
        def f(flag, obj):
            v = A() if flag else B()
            v.
            if isinstance(obj, B):
                obj.
        '''
        self.assertTrue({"a_method", "b_method"} <= set(self.complete(source, 7, 6)))
        names = self.complete(source, 9, 12)
        self.assertIn("b_method", names)
        self.assertNotIn("a_method", names)

    def test_dataclass_fields(self):
        source = '''\
        import dataclasses as dc
        @dc.dataclass
        class P:
            x: int
            y: str = ""
        P(1).
        '''
        self.assertTrue({"x", "y"} <= set(self.complete(source, 6, 5)))


if __name__ == "__main__":
    unittest.main()
