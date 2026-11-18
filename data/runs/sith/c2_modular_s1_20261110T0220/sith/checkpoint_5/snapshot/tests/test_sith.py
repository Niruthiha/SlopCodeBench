"""End-to-end tests for every `sith.py` command."""
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

    def run_sith(self, *args, command="complete"):
        return subprocess.run([sys.executable, SITH, command, *map(str, args)],
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


class NavigationTestCase(SithTestCase):
    def navigate(self, command, source, line, col, name="main.py"):
        path = self.write(name, source)
        result = self.run_sith(path, line, col, command=command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.endswith("\n"))
        definitions = json.loads(result.stdout)["definitions"]
        keys = [(d["module_path"], d["line"], d["column"]) for d in definitions]
        self.assertEqual(keys, sorted(keys))
        return definitions

    def infer(self, source, line, col, name="main.py"):
        return self.navigate("infer", source, line, col, name)

    def goto(self, source, line, col, name="main.py"):
        return self.navigate("goto", source, line, col, name)

    @staticmethod
    def summary(definitions):
        return [(d["name"], d["type"]) for d in definitions]


class InferTests(NavigationTestCase):
    SOURCE = """\
        class Calculator:
            \"\"\"Adds things.\"\"\"

            def __init__(self, value=0):
                self.value = value
                self.history = []

            def add(self, a, b):
                \"\"\"Add two numbers.\"\"\"
                return a + b

            def me(self):
                return self


        def make(flag):
            if flag:
                return Calculator()
            return "text"


        def nothing():
            pass


        calc = Calculator()
        other = calc
        """

    def test_class_instantiation(self):
        source = dedent(self.SOURCE) + "calc\n"
        self.assertEqual(self.infer(source, 28, 0), [{
            "name": "Calculator", "type": "instance", "full_name": "main.Calculator",
            "module_path": "main.py", "line": 1, "column": 6,
            "description": "instance of Calculator", "docstring": "Adds things."}])

    def test_class_and_function_names(self):
        source = dedent(self.SOURCE) + "Calculator\nmake\n"
        self.assertEqual(self.infer(source, 28, 0)[0]["type"], "class")
        self.assertEqual(self.infer(source, 28, 0)[0]["description"], "class Calculator")
        [function] = self.infer(source, 29, 0)
        self.assertEqual((function["type"], function["line"], function["column"]),
                         ("function", 16, 4))
        self.assertEqual(function["description"], "def make(flag)")
        self.assertEqual(function, self.goto(source, 29, 0)[0])

    def test_literals_and_builtins(self):
        source = "x = 5\ny = 'a'\nz = None\nx\ny\nz\n"
        self.assertEqual(self.infer(source, 4, 0), [{
            "name": "int", "type": "instance", "full_name": "builtins.int", "module_path": "",
            "line": 0, "column": 0, "description": "instance of int", "docstring": ""}])
        self.assertEqual(self.infer(source, 5, 0)[0]["full_name"], "builtins.str")
        self.assertEqual(self.infer(source, 6, 0)[0]["full_name"], "builtins.NoneType")

    def test_assignment_chain_and_method_calls(self):
        source = dedent(self.SOURCE) + "other\ncalc.add(1, 2)\ncalc.me().history\ncalc.value\n"
        self.assertEqual(self.summary(self.infer(source, 28, 0)), [("Calculator", "instance")])
        self.assertEqual(self.summary(self.infer(source, 29, 5)), [("add", "function")])
        self.assertEqual(self.summary(self.infer(source, 30, 12)), [("list", "instance")])
        self.assertEqual(self.summary(self.infer(source, 31, 6)), [("int", "instance")])

    def test_return_types(self):
        source = dedent(self.SOURCE) + "r = calc.add(1, 2)\nm = make(1)\nn = nothing()\nr\nm\nn\n"
        self.assertEqual(self.summary(self.infer(source, 31, 0)), [("int", "instance")])
        self.assertEqual(self.summary(self.infer(source, 32, 0)),
                         [("str", "instance"), ("Calculator", "instance")])
        self.assertEqual(self.summary(self.infer(source, 33, 0)), [("NoneType", "instance")])

    def test_constructor_arguments_flow_into_attributes(self):
        source = dedent(self.SOURCE) + "Calculator('s').value\n"
        self.assertEqual(self.summary(self.infer(source, 28, 17)), [("str", "instance")])

    def test_conditional_assignment(self):
        source = "import os\nif os.sep:\n    v = 1\nelse:\n    v = 'x'\nv\n"
        self.assertEqual(self.summary(self.infer(source, 6, 0)),
                         [("int", "instance"), ("str", "instance")])
        definitions = self.goto(source, 6, 0)
        self.assertEqual([(d["line"], d["column"], d["type"]) for d in definitions],
                         [(3, 4, "statement"), (5, 4, "statement")])

    def test_dataclass_fields(self):
        for header in ("import dataclasses\n@dataclasses.dataclass\n",
                       "from dataclasses import dataclass\n@dataclass(frozen=True)\n",
                       "from dataclasses import dataclass as dc\n@dc\n"):
            source = header + "class P:\n    x: int\n    y: list = None\np = P(1)\np.x\np.\n"
            self.assertEqual(self.summary(self.infer(source, 7, 2)), [("int", "instance")])
            completions = self.complete(source, 8, 2)
            self.assertEqual(self.names(completions), ["x", "y"])
            self.assertEqual(self.by_name(completions)["y"]["description"], "instance of list")

    def test_cross_module(self):
        self.write("pkg/__init__.py", "")
        self.write("pkg/shapes.py", "class Shape:\n    def area(self):\n        return 1.0\n")
        source = "from pkg.shapes import Shape\nimport pkg.shapes\ns = Shape()\ns.area()\ns\n"
        [area] = self.infer(source, 4, 3)
        self.assertEqual((area["full_name"], area["module_path"], area["line"], area["column"]),
                         ("pkg.shapes.Shape.area", os.path.join("pkg", "shapes.py"), 2, 8))
        self.assertEqual(self.summary(self.infer(source, 5, 0)), [("Shape", "instance")])
        [module] = self.infer(source, 2, 12)
        self.assertEqual((module["name"], module["type"], module["full_name"]),
                         ("shapes", "module", "pkg.shapes"))

    def test_unresolved_and_errors(self):
        self.assertEqual(self.infer("unknown_name\n", 1, 0), [])
        path = self.write("main.py", "x = 1  # note\ns = 'text'\n")
        for line, col in ((1, 2), (1, 3), (1, 4), (1, 10), (2, 6)):
            self.assertEqual(self.run_sith(path, line, col, command="infer").returncode, 1)
            self.assertEqual(self.run_sith(path, line, col, command="goto").returncode, 1)
        self.assertEqual(self.run_sith(path, 9, 0, command="infer").returncode, 1)
        self.assertEqual(self.run_sith(path, 1, 0, command="goto").returncode, 0)
        # A cursor just after an identifier is still on it.
        self.assertEqual(self.run_sith(path, 1, 1, command="infer").returncode, 0)


class NarrowingTests(NavigationTestCase):
    SOURCE = """\
        class Dog:
            def bark(self):
                pass


        class Cat:
            def meow(self):
                pass


        def maybe(flag):
            if flag:
                return Dog()
            return None


        pet = Dog() if maybe(1) else Cat()
        """

    def test_isinstance(self):
        source = dedent(self.SOURCE) + "if isinstance(pet, Dog):\n    pet\nelse:\n    pet\npet\n"
        self.assertEqual(self.summary(self.infer(source, 19, 4)), [("Dog", "instance")])
        self.assertEqual(self.summary(self.infer(source, 21, 4)), [("Cat", "instance")])
        self.assertEqual(self.summary(self.infer(source, 22, 0)),
                         [("Dog", "instance"), ("Cat", "instance")])

    def test_isinstance_of_unknown_value(self):
        source = dedent(self.SOURCE) + "def f(x):\n    if isinstance(x, (Cat, int)):\n        x\n"
        self.assertEqual(self.summary(self.infer(source, 20, 8)),
                         [("int", "instance"), ("Cat", "instance")])

    def test_is_none(self):
        source = dedent(self.SOURCE) + (
            "x = maybe(0)\nif x is None:\n    x\nelse:\n    x\n"
            "def f():\n    if x is None:\n        return\n    x\n")
        self.assertEqual(self.summary(self.infer(source, 20, 4)), [("NoneType", "instance")])
        self.assertEqual(self.summary(self.infer(source, 22, 4)), [("Dog", "instance")])
        self.assertEqual(self.summary(self.infer(source, 26, 4)), [("Dog", "instance")])

    def test_completion(self):
        source = dedent(self.SOURCE) + "pet.\nif isinstance(pet, Cat):\n    pet.\n"
        self.assertEqual(self.names(self.complete(source, 18, 4)), ["bark", "meow"])
        self.assertEqual(self.names(self.complete(source, 20, 8)), ["meow"])


class GotoTests(NavigationTestCase):
    SOURCE = """\
        import os
        from os import path as p


        class Base:
            def __init__(self, x):
                self.x = x

            def run(self, count):
                return count


        b = Base(1)
        b.run(2)
        """

    def test_definitions(self):
        source = dedent(self.SOURCE) + "b\nBase\nb.x\nos\np\n"
        self.assertEqual(self.goto(source, 15, 0), [{
            "name": "b", "type": "statement", "full_name": "main.b", "module_path": "main.py",
            "line": 13, "column": 0, "description": "Base(1)", "docstring": ""}])
        self.assertEqual(self.goto(source, 16, 0)[0]["description"], "class Base")
        [attribute] = self.goto(source, 17, 2)
        self.assertEqual((attribute["line"], attribute["column"], attribute["full_name"]),
                         (7, 13, "main.Base.x"))
        [module] = self.goto(source, 18, 0)
        self.assertEqual((module["type"], module["line"], module["description"]),
                         ("module", 1, "import os"))
        [alias] = self.goto(source, 19, 0)
        self.assertEqual((alias["line"], alias["column"], alias["description"]),
                         (2, 23, "from os import path as p"))

    def test_methods_and_parameters(self):
        source = dedent(self.SOURCE) + "b.run(count=3)\n"
        [method] = self.goto(source, 14, 3)
        self.assertEqual((method["line"], method["column"], method["description"]),
                         (9, 8, "def run(self, count)"))
        [param] = self.goto(source, 10, 15)
        self.assertEqual((param["type"], param["line"], param["column"], param["full_name"]),
                         ("param", 9, 18, "main.Base.run.count"))
        self.assertEqual(self.goto(source, 15, 7), [param])

    def test_properties_and_dataclass_keywords(self):
        source = ("from dataclasses import dataclass\n@dataclass\nclass P:\n    x: int\n"
                  "    @property\n    def double(self):\n        return [self.x]\n"
                  "p = P(x=1)\np.double\n")
        self.assertEqual(self.summary(self.infer(source, 9, 3)), [("list", "instance")])
        [method] = self.goto(source, 9, 3)
        self.assertEqual((method["line"], method["column"]), (6, 8))
        [field] = self.goto(source, 8, 6)
        self.assertEqual((field["line"], field["column"], field["description"]), (4, 4, "x: int"))

    def test_project_root(self):
        self.write("lib/tools.py", "def tool():\n    return 1\n")
        path = self.write("app/main.py", "from lib.tools import tool\ntool()\n")
        result = self.run_sith(path, 2, 0, "--project", self.dir, command="infer")
        self.assertEqual(result.returncode, 0, result.stderr)
        [tool] = json.loads(result.stdout)["definitions"]
        self.assertEqual((tool["full_name"], tool["module_path"]),
                         ("lib.tools.tool", os.path.join("lib", "tools.py")))
        result = self.run_sith(path, 2, 0, "--project", self.dir, command="goto")
        [binding] = json.loads(result.stdout)["definitions"]
        self.assertEqual((binding["full_name"], binding["module_path"], binding["column"]),
                         ("app.main.tool", os.path.join("app", "main.py"), 22))

    def test_definition_name_itself(self):
        source = "def foo():\n    pass\n\nfoo = foo\n"
        [function] = self.goto(source, 1, 5)
        self.assertEqual((function["line"], function["column"]), (1, 4))
        [assignment] = self.goto(source, 4, 0)
        self.assertEqual((assignment["line"], assignment["description"]), (4, "foo"))
        self.assertEqual(self.goto(source, 4, 7), [function])


class ImportTests(NavigationTestCase):
    def setUp(self):
        super().setUp()
        self.write("pkg/__init__.py", """\
            from .core import Engine
            __all__ = ["Engine", "helper", "_secret"]
            def helper(): pass
            _secret = 1
            other = 2
            """)
        self.write("pkg/core.py", """\
            import os
            from .util import tool as tool_alias

            class Engine:
                def start(self):
                    return 1

            def _private(): pass
            CONST = "x"
            """)
        self.write("pkg/util.py", "def tool(x):\n    return [x]\n")
        self.write("pkg/sub/__init__.py", "")
        self.write("pkg/sub/deep.py", "VAL = 3\n")
        self.write("ns/inner/mod.py", "def nsfunc():\n    return 1\n")

    def run_json(self, command, path, line, col, *flags):
        result = self.run_sith(path, line, col, *flags, command=command)
        self.assertEqual(result.returncode, 0, result.stderr)
        key = "completions" if command == "complete" else "definitions"
        return json.loads(result.stdout)[key]

    def test_goto_follow_imports(self):
        source = "from pkg import Engine\nfrom pkg.core import tool_alias\nEngine\ntool_alias\n"
        [site] = self.goto(source, 3, 0)
        self.assertEqual((site["module_path"], site["line"], site["column"], site["description"]),
                         ("main.py", 1, 16, "from pkg import Engine"))
        path = os.path.join(self.dir, "main.py")
        [engine] = self.run_json("goto", path, 3, 0, "--follow-imports")
        self.assertEqual((engine["full_name"], engine["module_path"], engine["line"], engine["column"]),
                         ("pkg.core.Engine", "pkg/core.py", 4, 6))
        [tool] = self.run_json("goto", path, 4, 0, "--follow-imports")
        self.assertEqual((tool["full_name"], tool["module_path"], tool["line"]),
                         ("pkg.util.tool", "pkg/util.py", 1))
        [module] = self.run_json("goto", path, 1, 6, "--follow-imports")
        self.assertEqual((module["type"], module["module_path"]), ("module", "pkg/__init__.py"))

    def test_follow_imports_fallback(self):
        self.write("helper.py", "from os.path import join\n")
        source = "import os\nfrom helper import join\nfrom nowhere import thing\nos\njoin\nthing\n"
        path = self.write("main.py", source)
        for line, expected in ((4, (1, 7)), (5, (2, 19)), (6, (3, 20))):
            [site] = self.run_json("goto", path, line, 0, "--follow-imports")
            self.assertEqual((site["module_path"], site["line"], site["column"]),
                             ("main.py",) + expected)

    def test_infer_across_files(self):
        source = ("import pkg.sub.deep\nfrom ns.inner.mod import nsfunc\nfrom pkg import Engine\n"
                  "pkg.sub.deep.VAL\nnsfunc()\nEngine().start()\n")
        self.assertEqual(self.summary(self.infer(source, 4, 13)), [("int", "instance")])
        [nsfunc] = self.infer(source, 5, 0)
        self.assertEqual((nsfunc["full_name"], nsfunc["module_path"]), ("ns.inner.mod.nsfunc",
                                                                        "ns/inner/mod.py"))
        self.assertEqual(self.summary(self.infer(source, 6, 10)), [("start", "function")])

    def test_unresolvable_modules(self):
        source = "import pip\nimport nothere\npip\nnothere.x\n"
        self.assertEqual(self.infer(source, 3, 0), [])
        self.assertEqual(self.infer(source, 4, 8), [])
        self.assertEqual(self.complete(source + "nothere.\n", 5, 8), [])

    def test_relative_imports(self):
        path = self.write("pkg/rel.py", "from . import util\nfrom .. import ns\nutil.tool\nns\n")
        [tool] = self.run_json("infer", path, 3, 6)
        self.assertEqual(tool["module_path"], "util.py")
        self.assertEqual(self.run_json("infer", path, 4, 0), [])
        [tool] = self.run_json("infer", path, 3, 6, "--project", self.dir)
        self.assertEqual((tool["full_name"], tool["module_path"]), ("pkg.util.tool", "pkg/util.py"))
        [ns] = self.run_json("infer", path, 4, 0, "--project", self.dir)
        self.assertEqual((ns["type"], ns["full_name"]), ("module", "ns"))

    def test_star_import_all(self):
        source = "from pkg import *\n\n"
        names = self.names(self.complete(source, 2, 0), include_keywords=False)
        self.assertIn("Engine", names)
        self.assertIn("_secret", names)
        self.assertNotIn("other", names)
        source = "from pkg.core import *\n\n"
        names = self.names(self.complete(source, 2, 0), include_keywords=False)
        self.assertIn("CONST", names)
        self.assertNotIn("_private", names)

    def test_circular_imports(self):
        self.write("a.py", "from b import *\nfrom b import bfunc\nA = 1\ndef afunc():\n    return 1\n")
        self.write("b.py", "from a import *\nfrom a import afunc\nB = 2\ndef bfunc():\n    return afunc()\n")
        source = "from a import *\nA\nB\nbfunc()\n"
        self.assertEqual(self.summary(self.infer(source, 2, 0)), [("int", "instance")])
        self.assertEqual(self.summary(self.infer(source, 3, 0)), [("int", "instance")])
        self.assertEqual(self.summary(self.infer(source, 4, 0)), [("bfunc", "function")])

    def test_import_completion(self):
        source = "import \nimport pk\nimport pkg.\nfrom pkg import \nfrom pkg.core import _\nfrom pkg \n"
        names = self.names(self.complete(source, 1, 7))
        self.assertLess(names.index("pkg"), names.index("_thread"))
        self.assertLess(names.index("_thread"), names.index("__future__"))
        self.assertIn("ns", names)
        self.assertIn("os", names)
        self.assertNotIn("pip", names)
        result = self.complete(source, 2, 9)
        self.assertEqual(result[0], {"name": "pkg", "complete": "g", "type": "module",
                                     "description": "module pkg"})
        self.assertEqual(self.names(self.complete(source, 3, 11)), ["core", "sub", "util"])
        self.assertEqual(self.names(self.complete(source, 4, 16)), ["Engine", "helper", "_secret"])
        self.assertEqual(self.names(self.complete(source, 5, 22)), [])
        self.assertEqual(self.names(self.complete(source, 6, 9)), ["import"])
        names = self.names(self.complete("from pkg.core import (CONST,\n    \n", 2, 4))
        self.assertEqual(names, ["CONST", "Engine", "os", "tool_alias"])
        self.assertEqual(self.complete("import os as \n", 1, 13), [])

    def test_cross_file_attribute_completion(self):
        source = "import pkg\nfrom pkg import Engine\npkg.\nEngine().\n"
        self.assertEqual(self.names(self.complete(source, 3, 4)),
                         ["core", "Engine", "helper", "other", "sub", "util"])
        self.assertEqual(self.names(self.complete(source, 4, 9)), ["start"])


class CommandTestCase(SithTestCase):
    def run_json(self, command, *args, key=None):
        result = subprocess.run([sys.executable, SITH, command, *map(str, args)],
                                capture_output=True, text=True, cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.endswith("\n"))
        return json.loads(result.stdout)[key or command]

    def signatures(self, source, line, col, name="main.py"):
        path = self.write(name, source)
        return self.run_json("signatures", path, line, col)

    def references(self, path, line, col, *flags):
        return [(r["module_path"], r["line"], r["column"], r["is_definition"])
                for r in self.run_json("references", path, line, col, *flags)]


class SignatureTests(CommandTestCase):
    SOURCE = """\
        class Calculator:
            \"\"\"Adds things.\"\"\"

            def __init__(self, value=0):
                self.value = value

            def add(self, a, b: int = 2, *rest, scale: float = 1.0, **options) -> int:
                \"\"\"Add two numbers.\"\"\"
                return a + b


        def plain(x, y, /, z, *, flag=False):
            pass


        calc = Calculator()
        """

    def test_method_signature(self):
        source = dedent(self.SOURCE) + "calc.add(1, \n"
        [signature] = self.signatures(source, 17, 12)
        self.assertEqual(signature, {
            "name": "add",
            "params": ["a", "b: int=2", "*rest", "scale: float=1.0", "**options"],
            "index": 1,
            "description": "def add(a, b: int=2, *rest, scale: float=1.0, **options) -> int",
            "docstring": "Add two numbers."})

    def test_parameter_binding(self):
        source = dedent(self.SOURCE) + "calc.add(1, 2, 3, scale=2, other=1, **{})\nplain(1, 2, 3, w=1)\n"
        index = lambda col, line=17: self.signatures(source, line, col)[0]["index"]
        self.assertEqual(index(9), 0)
        self.assertEqual(index(15), 2)  # extra positional -> *rest
        self.assertEqual(index(24), 3)  # scale=
        self.assertEqual(index(33), 4)  # unknown keyword -> **options
        self.assertEqual(index(39), 4)  # **{} -> **options
        self.assertEqual(index(6, 18), 0)
        self.assertEqual(index(12, 18), 2)
        self.assertIsNone(index(15, 18))  # unknown keyword without **kwargs
        [signature] = self.signatures(source, 18, 6)
        self.assertEqual(signature["params"], ["x", "y", "z", "flag=False"])

    def test_past_all_parameters(self):
        source = "def one(a):\n    pass\none(1, 2)\n"
        self.assertIsNone(self.signatures(source, 3, 7)[0]["index"])

    def test_class_and_constructor(self):
        source = dedent(self.SOURCE) + "Calculator(\n"
        [signature] = self.signatures(source, 17, 11)
        self.assertEqual((signature["name"], signature["params"], signature["index"],
                          signature["docstring"]), ("Calculator", ["value=0"], 0, "Adds things."))

    def test_not_in_call(self):
        source = dedent(self.SOURCE) + "x = (1, 2)\ncalc.add(1)\ndef f(a, b):\n    pass\n"
        self.assertEqual(self.signatures(source, 17, 5), [])
        self.assertEqual(self.signatures(source, 18, 4), [])
        self.assertEqual(self.signatures(source, 18, 11), [])
        self.assertEqual(self.signatures(source, 19, 9), [])

    def test_nested_brackets_and_strings(self):
        source = dedent(self.SOURCE) + 'plain("a,(", [1, 2], {3: (4, 5)}, \n'
        self.assertEqual(self.signatures(source, 17, 21)[0]["index"], 2)
        self.assertIsNone(self.signatures(source, 17, 34)[0]["index"])
        source = dedent(self.SOURCE) + "plain(calc.add(1, 2), [3, \n"
        self.assertEqual(self.signatures(source, 17, 26)[0]["index"], 1)
        [inner] = self.signatures(source, 17, 18)
        self.assertEqual((inner["name"], inner["index"]), ("add", 1))

    def test_multiple_and_overloaded(self):
        source = ("from typing import overload\n@overload\ndef h(x: int) -> int: ...\n"
                  "@overload\ndef h(x: str) -> str: ...\ndef h(x):\n    return x\n"
                  "def k(a):\n    pass\npick = h if x else k\nh(\npick(\n")
        self.assertEqual([s["description"] for s in self.signatures(source, 11, 2)],
                         ["def h(x: int) -> int", "def h(x: str) -> str"])
        self.assertEqual([s["name"] for s in self.signatures(source, 12, 5)], ["h", "h", "k"])

    def test_builtin(self):
        [signature] = self.signatures("len(\n", 1, 4)
        self.assertEqual((signature["name"], signature["params"], signature["index"]),
                         ("len", ["obj"], 0))


class StubTests(CommandTestCase):
    def setUp(self):
        super().setUp()
        self.write("mylib.py", """\
            def greet(name, times=1):
                \"\"\"Greets.\"\"\"
                return make(name) * times

            class Config:
                def __init__(self, path):
                    self.path = path
                    self.data = load(path)

            VERSION = make_version()
            """)
        self.write("mylib.pyi", """\
            from typing import overload

            class Config:
                path: str
                data: dict
                debug: bool
                def __init__(self, path: str) -> None: ...

            def greet(name: str, times: int = 1) -> str: ...

            VERSION: str

            def stub_only(x: int) -> float: ...

            @overload
            def conv(x: int) -> str: ...
            @overload
            def conv(x: str) -> int: ...
            """)
        self.write("stubs/extlib.pyi", "class Client:\n    url: str\ndef connect() -> Client: ...\n")

    def infer_names(self, path, line, col):
        return [d["name"] for d in self.run_json("infer", path, line, col, key="definitions")]

    def test_signatures_and_inference_from_stub(self):
        path = self.write("main.py", "from mylib import greet, VERSION, stub_only, conv\n"
                                     "r = greet('x')\nr\nVERSION\nstub_only(1)\nconv(1)\n"
                                     "conv('s')\ngreet(\n")
        [signature] = self.run_json("signatures", path, 8, 6)
        self.assertEqual(signature["params"], ["name: str", "times: int=1"])
        self.assertEqual(signature["description"], "def greet(name: str, times: int=1) -> str")
        self.assertEqual(signature["docstring"], "Greets.")
        self.assertEqual(self.infer_names(path, 3, 0), ["str"])
        self.assertEqual(self.infer_names(path, 4, 0), ["str"])
        self.assertEqual(self.infer_names(path, 5, 3), ["stub_only"])
        result = subprocess.run([sys.executable, SITH, "infer", path, "6", "0"],
                                capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout)["definitions"][0]["name"], "conv")

    def test_overload_return(self):
        path = self.write("main.py", "from mylib import conv\na = conv(1)\nb = conv('s')\na\nb\n")
        self.assertEqual(self.infer_names(path, 4, 0), ["str"])
        self.assertEqual(self.infer_names(path, 5, 0), ["int"])

    def test_completion_and_goto(self):
        path = self.write("main.py", "from mylib import Config, stub_only\nc = Config('p')\n"
                                     "c.path\nc.debug\nc.\n")
        completions = {c["name"]: c["description"]
                       for c in self.run_json("complete", path, 5, 2, key="completions")}
        self.assertEqual(completions["data"], "instance of dict")
        self.assertEqual(completions["debug"], "instance of bool")
        self.assertEqual(completions["path"], "instance of str")
        [source] = self.run_json("goto", path, 3, 2, key="definitions")
        self.assertEqual((source["module_path"], source["line"]), ("mylib.py", 7))
        [stub] = self.run_json("goto", path, 4, 2, key="definitions")
        self.assertEqual((stub["module_path"], stub["line"]), ("mylib.pyi", 6))
        [function] = self.run_json("goto", path, 1, 18, "--follow-imports", key="definitions")
        self.assertEqual((function["module_path"], function["line"]), ("mylib.py", 5))

    def test_stub_directory(self):
        path = self.write("main.py", "import extlib\nc = extlib.connect()\nc.url\n")
        self.assertEqual(self.infer_names(path, 3, 2), ["str"])
        [client] = self.run_json("infer", path, 2, 0, key="definitions")
        self.assertEqual((client["name"], client["module_path"]), ("Client", "stubs/extlib.pyi"))


class DynamicParameterTests(CommandTestCase):
    SOURCE = """\
        def process(data, flag=None):
            return data

        class Box:
            def __init__(self, item):
                self.item = item

        def typed(x: int, y):
            return y

        process(42)
        process("s", flag=True)
        Box([1]).item
        typed(1, "q")
        """

    def infer_names(self, line, col):
        path = self.write("main.py", self.SOURCE)
        return [d["name"] for d in self.run_json("infer", path, line, col, key="definitions")]

    def test_call_sites(self):
        self.assertEqual(self.infer_names(2, 11), ["int", "str"])
        self.assertEqual(self.infer_names(1, 18), ["NoneType", "bool"])
        self.assertEqual(self.infer_names(6, 20), ["list"])
        self.assertEqual(self.infer_names(9, 11), [])

    def test_other_files_not_searched(self):
        self.write("caller.py", "from lib import work\nwork(1)\n")
        path = self.write("lib.py", "def work(v):\n    return v\n")
        self.assertEqual(self.run_json("infer", path, 2, 11, key="definitions"), [])


class ReferenceTests(CommandTestCase):
    def setUp(self):
        super().setUp()
        self.write("pkg/__init__.py", "")
        self.calc = self.write("pkg/calc.py", """\
            class Calculator:
                def __init__(self, value=0):
                    self.value = value

                def calculate(self, x):
                    return x * self.value

            def recalculate(c):
                value = 3
                return c.calculate(value)
            """)
        self.main = self.write("main.py", """\
            from pkg.calc import Calculator
            from pkg import calc as calcmod

            c = Calculator(3)
            c.value
            calcmod.Calculator

            def other():
                value = 1
                return value
            """)

    def test_file_scope(self):
        self.assertEqual(self.references(self.main, 4, 5), [
            ("main.py", 1, 21, True), ("main.py", 4, 4, False), ("main.py", 6, 8, False)])
        self.assertEqual(self.references(self.main, 10, 11), [
            ("main.py", 9, 4, True), ("main.py", 10, 11, False)])

    def test_project_scope(self):
        self.assertEqual(self.references(self.main, 4, 5, "--scope", "project"), [
            ("main.py", 1, 21, True), ("main.py", 4, 4, False), ("main.py", 6, 8, False),
            ("pkg/calc.py", 1, 6, True)])
        self.assertEqual(self.references(self.calc, 3, 14, "--scope", "project",
                                         "--project", self.dir), [
            ("main.py", 5, 2, False), ("pkg/calc.py", 3, 13, True), ("pkg/calc.py", 6, 24, False)])

    def test_same_spelling_other_scope(self):
        self.assertEqual(self.references(self.calc, 9, 4, "--scope", "project",
                                         "--project", self.dir), [
            ("pkg/calc.py", 9, 4, True), ("pkg/calc.py", 10, 23, False)])

    def test_not_a_name(self):
        result = subprocess.run([sys.executable, SITH, "references", self.main, "3", "0"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)


class SearchAndNamesTests(CommandTestCase):
    def setUp(self):
        super().setUp()
        self.write("calc.py", """\
            import os
            CALC = 1

            class Calculator:
                rate = 2

                def recalculate(self):
                    calc_local = 3
                    return calc_local

            def calc():
                pass
            """)
        self.write("util/helpers.py", "def precalc():\n    pass\n")

    def test_search(self):
        results = self.run_json("search", "calc", "--project", self.dir, key="definitions")
        self.assertEqual([(r["name"], r["module_path"], r["line"]) for r in results], [
            ("CALC", "calc.py", 2), ("calc", "calc.py", 11), ("Calculator", "calc.py", 4),
            ("recalculate", "calc.py", 7), ("precalc", "util/helpers.py", 1)])
        self.assertNotIn("docstring", results[0])
        self.assertEqual(results[3]["full_name"], "calc.Calculator.recalculate")

    def test_names(self):
        path = os.path.join(self.dir, "calc.py")
        names = self.run_json("names", path, key="names")
        self.assertEqual([(n["name"], n["line"], n["column"]) for n in names],
                         [("os", 1, 7), ("CALC", 2, 0), ("Calculator", 4, 6), ("calc", 11, 4)])
        self.assertTrue(all(n["is_definition"] for n in names))
        names = self.run_json("names", path, "--all-scopes", key="names")
        self.assertEqual([n["name"] for n in names], [
            "os", "CALC", "Calculator", "rate", "recalculate", "self", "calc_local", "calc"])


class RefactoringTestCase(CommandTestCase):
    def refactor(self, command, *args):
        result = subprocess.run([sys.executable, SITH, command, *map(str, args)],
                                capture_output=True, text=True, cwd=self.dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def fails(self, command, *args):
        result = subprocess.run([sys.executable, SITH, command, *map(str, args)],
                                capture_output=True, text=True, cwd=self.dir)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        return result.stderr


class RenameTests(RefactoringTestCase):
    def setUp(self):
        super().setUp()
        self.write("shapes/__init__.py", "from .circle import Circle\n")
        self.write("shapes/circle.py", """\
            class Circle:
                def __init__(self, radius):
                    self.radius = radius

                def area(self, scale=1):
                    return 3.14 * self.radius ** 2 * scale
            """)
        self.app = self.write("app.py", """\
            import shapes.circle
            from shapes import Circle

            def run(scale):
                c = Circle(radius=2)
                total = c.area(scale=scale)
                return total + shapes.circle.Circle(1).radius
            """)

    def test_rename_class_across_files(self):
        result = self.refactor("rename", self.app, 5, 9, "--new-name", "Ring")
        self.assertEqual(result["renames"], {})
        self.assertEqual(sorted(result["changed_files"]),
                         ["app.py", "shapes/__init__.py", "shapes/circle.py"])
        self.assertIn("c = Ring(radius=2)", result["changed_files"]["app.py"])
        self.assertIn("shapes.circle.Ring(1)", result["changed_files"]["app.py"])
        self.assertEqual(result["changed_files"]["shapes/__init__.py"], "from .circle import Ring\n")
        self.assertTrue(result["changed_files"]["shapes/circle.py"].startswith("class Ring:"))

    def test_rename_parameter_and_keyword_arguments(self):
        result = self.refactor("rename", os.path.join(self.dir, "shapes/circle.py"), 2, 24,
                               "--new-name", "size", "--project", self.dir)
        self.assertIn("c = Circle(size=2)", result["changed_files"]["app.py"])
        self.assertIn("def __init__(self, size):\n        self.radius = size",
                      result["changed_files"]["shapes/circle.py"])

    def test_rename_module_and_package(self):
        result = self.refactor("rename", self.app, 1, 16, "--new-name", "round")
        self.assertEqual(result["renames"], {"shapes/circle.py": "shapes/round.py"})
        self.assertIn("import shapes.round\n", result["changed_files"]["app.py"])
        self.assertEqual(result["changed_files"]["shapes/__init__.py"], "from .round import Circle\n")
        result = self.refactor("rename", self.app, 1, 8, "--new-name", "geometry")
        self.assertEqual(result["renames"], {"shapes": "geometry"})
        self.assertIn("from geometry import Circle", result["changed_files"]["app.py"])
        self.assertTrue(os.path.exists(os.path.join(self.dir, "shapes")))  # nothing is written

    def test_diff(self):
        result = subprocess.run([sys.executable, SITH, "rename", self.app, "4", "8",
                                 "--new-name", "factor", "--diff"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--- app.py\n+++ app.py\n", result.stdout)
        self.assertIn("-def run(scale):\n+def run(factor):\n", result.stdout)
        self.assertIn("+    total = c.area(scale=factor)\n", result.stdout)

    def test_validation(self):
        self.fails("rename", self.app, 4, 4, "--new-name", "1x")
        self.fails("rename", self.app, 4, 4, "--new-name", "class")
        self.fails("rename", self.app, 4, 0, "--new-name", "fine")
        self.assertIn("total", self.fails("rename", self.app, 5, 4, "--new-name", "total"))


class InlineTests(RefactoringTestCase):
    def test_parentheses(self):
        path = self.write("main.py", """\
            def f(a, b):
                x = a + b
                y = x * 2
                print(x, -x, x.real, x ** 2)
                return y
            """)
        result = self.refactor("inline", path, 2, 4)
        self.assertEqual(result["changed_files"]["main.py"], dedent("""\
            def f(a, b):
                y = (a + b) * 2
                print(a + b, -(a + b), (a + b).real, (a + b) ** 2)
                return y
            """))

    def test_across_modules(self):
        self.write("conf.py", "LIMIT = 10\nNAME = 'n'\n")
        path = self.write("use.py", "from conf import LIMIT, NAME\nprint(LIMIT + 1, NAME)\n")
        result = self.refactor("inline", path, 2, 6)
        self.assertEqual(result["changed_files"], {
            "conf.py": "NAME = 'n'\n",
            "use.py": "from conf import NAME\nprint(10 + 1, NAME)\n"})

    def test_errors(self):
        path = self.write("main.py", "def f():\n    pass\nunused = 1\nf()\n")
        self.assertIn("cannot inline a function/class definition", self.fails("inline", path, 1, 4))
        self.assertIn("name has no references to inline", self.fails("inline", path, 3, 0))


class ExtractTests(RefactoringTestCase):
    def test_extract_variable(self):
        path = self.write("main.py", "def f(a, b):\n    return (a + b) * 2\n")
        result = self.refactor("extract-variable", path, 2, 12, "--until", "2:17", "--name", "s")
        self.assertEqual(result["changed_files"]["main.py"],
                         "def f(a, b):\n    s = a + b\n    return s * 2\n")
        self.assertIn("selection is not a complete expression",
                      self.fails("extract-variable", path, 2, 12, "--until", "2:21", "--name", "s"))
        self.fails("extract-variable", path, 2, 12, "--until", "2:17", "--name", "not valid")

    def test_extract_function(self):
        path = self.write("main.py", """\
            def compute(a, b):
                total = a + b
                doubled = total * 2
                scaled = doubled + a
                return scaled, total
            """)
        result = self.refactor("extract-function", path, 2, 0, "--until", "3:23", "--name", "part")
        self.assertEqual(result["changed_files"]["main.py"], dedent("""\
            def part(a, b):
                total = a + b
                doubled = total * 2
                return total, doubled


            def compute(a, b):
                total, doubled = part(a, b)
                scaled = doubled + a
                return scaled, total
            """))
        self.fails("extract-function", path, 2, 4, "--until", "3:10", "--name", "part")

    def test_extract_function_module_level_and_method(self):
        path = self.write("main.py", """\
            data = [1, 2]
            total = sum(data)
            print(total)

            class A:
                def m(self, r):
                    base = r * self.k
                    return base
            """)
        result = self.refactor("extract-function", path, 2, 0, "--until", "2:17", "--name", "g")
        self.assertIn("data = [1, 2]\ndef g(data):\n    total = sum(data)\n    return total\n",
                      result["changed_files"]["main.py"])
        self.assertIn("\ntotal = g(data)\nprint(total)", result["changed_files"]["main.py"])
        result = self.refactor("extract-function", path, 7, 0, "--until", "7:25", "--name", "g")
        self.assertIn("    def g(self, r):\n        base = r * self.k\n        return base\n",
                      result["changed_files"]["main.py"])
        self.assertIn("        base = self.g(r)\n", result["changed_files"]["main.py"])


class SyntaxErrorTests(CommandTestCase):
    def test_errors(self):
        path = self.write("bad.py", "def f(:\n    pass\nx = (1 +\n")
        errors = self.run_json("errors", path)
        self.assertEqual([(e["line"], e["column"]) for e in errors], [(1, 6), (3, 4)])
        self.assertTrue(all(e["message"] for e in errors))
        self.assertEqual(self.run_json("errors", self.write("ok.py", "x = 1\n")), [])
        missing = subprocess.run([sys.executable, SITH, "errors", "missing.py"],
                                 capture_output=True, text=True, cwd=self.dir)
        self.assertEqual(missing.returncode, 1)


if __name__ == "__main__":
    unittest.main()
