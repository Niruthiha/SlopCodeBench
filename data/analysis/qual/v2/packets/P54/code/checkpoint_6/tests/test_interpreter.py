"""End-to-end tests for interpreter mode, ``context``, settings, project
configuration and the ``env`` commands."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

SITH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sith.py")

MAIN = '''\
    import os


    class Shape:
        def area(self, scale):
            total = scale
            return total

        async def grow(self):
            def inner():
                pass
            return 1


    def helper(a, b=2):
        return a


    local_value = 1
    runtime_num
    mod.
    data.
    mystery(
    local_value
    Obj.
    '''

NAMESPACES = [
    {"runtime_num": {"type": "int", "value": "42"},
     "runtime_other": {"type": "list"},
     "mod": {"type": "module", "name": "os"},
     "data": {"type": "dict"},
     "mystery": {"type": "function", "value": "Does things."},
     "local_value": {"type": "str"},
     "Obj": {"type": "class", "module": "app", "attributes": ["alpha", "beta"]}},
    {"runtime_num": {"type": "str"},
     "runtime_late": {"type": "float"}},
]


class SithTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name, text):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(textwrap.dedent(text))
        return path

    def run_sith(self, *args, cwd=None, env=None):
        return subprocess.run([sys.executable, SITH] + [str(a) for a in args],
                              capture_output=True, text=True, cwd=cwd or self.root, env=env)

    def json_of(self, *args, **kwargs):
        completed = self.run_sith(*args, **kwargs)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)


class InterpreterTest(SithTestCase):
    def setUp(self):
        super().setUp()
        self.main = self.write("main.py", MAIN)
        self.namespaces = self.write("ns.json", json.dumps(NAMESPACES))

    def interpreter(self, command, line, col):
        return self.json_of(command, self.main, line, col, "--interpreter",
                            "--namespaces", self.namespaces)

    def test_completion_merges_namespaces_first_match_wins(self):
        found = self.interpreter("complete", 20, 8)["completions"]
        by_name = {c["name"]: c for c in found}
        self.assertEqual(by_name["runtime_num"],
                         {"name": "runtime_num", "complete": "num", "type": "int",
                          "description": "int (runtime)"})
        self.assertEqual(by_name["runtime_other"]["description"], "list (runtime)")
        self.assertEqual(by_name["runtime_late"]["type"], "float")

    def test_static_names_win_over_namespaces(self):
        found = self.interpreter("complete", 24, 5)["completions"]
        local = [c for c in found if c["name"] == "local_value"]
        self.assertEqual(local[0]["description"], "instance of int")
        definitions = self.interpreter("infer", 24, 3)["definitions"]
        self.assertEqual([d["name"] for d in definitions], ["int"])

    def test_infer_and_goto_fall_back_to_namespaces(self):
        for command in ("infer", "goto"):
            definitions = self.interpreter(command, 20, 3)["definitions"]
            self.assertEqual(len(definitions), 1)
            self.assertEqual(definitions[0]["type"], "int")
            self.assertEqual(definitions[0]["description"], "int (runtime)")
            self.assertEqual(definitions[0]["docstring"], "42")

    def test_attribute_completion_of_namespace_values(self):
        names = [c["name"] for c in self.interpreter("complete", 21, 4)["completions"]]
        self.assertIn("getcwd", names)
        names = [c["name"] for c in self.interpreter("complete", 22, 5)["completions"]]
        self.assertIn("keys", names)
        names = [c["name"] for c in self.interpreter("complete", 25, 4)["completions"]]
        self.assertEqual(names[:2], ["alpha", "beta"])

    def test_signatures_of_namespace_function(self):
        found = self.interpreter("signatures", 23, 8)["signatures"]
        self.assertEqual(found[0]["name"], "mystery")
        self.assertEqual(found[0]["docstring"], "Does things.")

    def test_interpreter_without_namespaces_is_normal_mode(self):
        normal = self.json_of("complete", self.main, 20, 8)
        self.assertEqual(self.json_of("complete", self.main, 20, 8, "--interpreter"), normal)
        self.assertEqual(normal["completions"], [])

    def test_namespaces_without_interpreter_fails(self):
        completed = self.run_sith("complete", self.main, 20, 7, "--namespaces", self.namespaces)
        self.assertEqual(completed.returncode, 1)
        self.assertTrue(completed.stderr)

    def test_bad_namespaces_file_fails(self):
        bad = self.write("bad.json", "{}")
        completed = self.run_sith("complete", self.main, 20, 7, "--interpreter",
                                  "--namespaces", bad)
        self.assertEqual(completed.returncode, 1)


class ContextTest(SithTestCase):
    def setUp(self):
        super().setUp()
        self.main = self.write("main.py", MAIN)

    def context(self, line, col):
        return self.json_of("context", self.main, line, col)["context"]

    def test_module_level_is_empty(self):
        self.assertEqual(self.context(19, 0), [])

    def test_nested_scopes_outermost_first(self):
        self.assertEqual(self.context(6, 8), [
            {"name": "Shape", "type": "class", "line": 4, "column": 6},
            {"name": "area", "type": "function", "line": 5, "column": 8}])
        self.assertEqual([s["name"] for s in self.context(11, 16)], ["Shape", "grow", "inner"])
        self.assertEqual(self.context(16, 4),
                         [{"name": "helper", "type": "function", "line": 15, "column": 4}])


class SettingsTest(SithTestCase):
    def setUp(self):
        super().setUp()
        self.main = self.write("m.py", '''\
            def func(p):
                return p


            func(1)
            Value = 1
            value_two = 2
            val
            fu
            ''')

    def names(self, *extra):
        found = self.json_of("complete", self.main, 8, 3, *extra)["completions"]
        return [c["name"] for c in found]

    def test_case_insensitive(self):
        self.assertIn("Value", self.names())
        self.assertEqual(self.names("--setting", "case_insensitive=false"), ["value_two"])
        self.assertIn("Value", self.names("--setting", "case_insensitive=TRUE"))

    def test_add_bracket(self):
        found = self.json_of("complete", self.main, 9, 2, "--setting", "add_bracket=true")
        func = [c for c in found["completions"] if c["name"] == "func"][0]
        self.assertEqual(func["complete"], "nc(")

    def test_dynamic_params(self):
        self.assertEqual(len(self.json_of("infer", self.main, 2, 12)["definitions"]), 1)
        found = self.json_of("infer", self.main, 2, 12, "--setting", "dynamic_params=false")
        self.assertEqual(found["definitions"], [])

    def test_invalid_settings_fail(self):
        for setting in ("nonsense=true", "add_bracket=maybe", "add_bracket"):
            completed = self.run_sith("complete", self.main, 8, 3, "--setting", setting)
            self.assertEqual(completed.returncode, 1, setting)

    def test_cli_overrides_project_config(self):
        os.makedirs(os.path.join(self.root, ".sith"))
        self.write(".sith/project.json", '{"case_insensitive": false}')
        self.assertEqual(self.names(), ["value_two"])
        self.assertIn("Value", self.names("--setting", "case_insensitive=true"))


class ProjectTest(SithTestCase):
    def setUp(self):
        super().setUp()
        self.write("src/mylib/__init__.py", "def libfunc():\n    pass\n")
        self.write("extra/extramod.py", "EXTRA = 1\n")
        self.write("app/sibling.py", "SIB = 1\n")
        self.main = self.write("app/main.py", '''\
            import mylib
            import extramod
            import sibling
            mylib.libfunc
            extramod.EXTRA
            sibling.SIB
            ''')

    def config(self):
        with open(os.path.join(self.root, ".sith", "project.json")) as handle:
            return json.load(handle)

    def resolves(self, line, col):
        found = self.json_of("infer", self.main, line, col, "--project", self.root)
        return bool(found["definitions"])

    def test_init_defaults_and_merge(self):
        self.json_of("project", "init")
        self.assertEqual(self.config(), {"environment_path": "", "sys_path": [],
                                         "added_sys_path": [], "smart_sys_path": True})
        self.json_of("project", "init", self.root, "--environment", "/usr/bin/python3")
        self.json_of("project", "init", self.root, "--added-sys-path", "a,b")
        self.assertEqual(self.config(), {"environment_path": "/usr/bin/python3",
                                         "sys_path": [], "added_sys_path": ["a", "b"],
                                         "smart_sys_path": True})

    def test_init_creates_directory(self):
        target = os.path.join(self.root, "new")
        self.json_of("project", "init", target, "--sys-path", "x")
        self.assertTrue(os.path.isfile(os.path.join(target, ".sith", "project.json")))

    def test_added_sys_path(self):
        self.assertFalse(self.resolves(4, 7))
        self.json_of("project", "init", "--added-sys-path", "src")
        self.assertTrue(self.resolves(4, 7))
        found = self.json_of("infer", self.main, 4, 7, "--project", self.root)
        self.assertEqual(found["definitions"][0]["full_name"], "mylib.libfunc")

    def test_sys_path_replaces_auto_detection(self):
        self.assertTrue(self.resolves(6, 9))
        self.json_of("project", "init", "--sys-path", "extra")
        self.assertTrue(self.resolves(5, 10))
        self.assertFalse(self.resolves(6, 9))

    def test_smart_sys_path_false(self):
        self.json_of("project", "init", "--added-sys-path", "src",
                     "--setting", "smart_sys_path=false")
        self.assertIs(self.config()["smart_sys_path"], False)
        self.assertTrue(self.resolves(4, 7))
        self.assertFalse(self.resolves(6, 9))
        found = self.json_of("infer", self.main, 6, 9, "--project", self.root,
                             "--setting", "smart_sys_path=true")
        self.assertTrue(found["definitions"])


class EnvTest(SithTestCase):
    def test_list(self):
        environments = self.json_of("env", "list")["environments"]
        self.assertTrue(environments)
        for environment in environments:
            self.assertEqual(set(environment), {"executable", "version", "is_virtualenv"})
            self.assertTrue(os.path.isabs(environment["executable"]))
        resolved = [os.path.realpath(e["executable"]) for e in environments]
        self.assertEqual(len(resolved), len(set(resolved)))
        self.assertIn(os.path.realpath(sys.executable), resolved)
        keys = [(tuple(-int(p) for p in e["version"].split(".")), e["executable"])
                for e in environments]
        self.assertEqual(keys, sorted(keys))

    def test_find_virtualenvs(self):
        venvs = os.path.join(self.root, "venvs")
        subprocess.run([sys.executable, "-m", "venv", "--without-pip",
                        os.path.join(venvs, "real")], check=True)
        self.write("venvs/fake/pyvenv.cfg", "version = 3.9.1\n")
        self.write("venvs/fake/bin/python", "")
        self.write("venvs/plain/readme.txt", "")
        env = dict(os.environ, HOME=self.root)
        found = self.json_of("env", "find-virtualenvs", "--path", venvs, env=env)
        found = found["environments"]
        self.assertEqual([e["executable"] for e in found],
                         [os.path.join(venvs, "real", "bin", "python"),
                          os.path.join(venvs, "fake", "bin", "python")])
        self.assertTrue(all(e["is_virtualenv"] for e in found))
        self.assertEqual(found[1]["version"], "3.9.1")

    def test_info(self):
        info = self.json_of("env", "info", sys.executable)
        self.assertEqual(info["version"], "%d.%d.%d" % sys.version_info[:3])
        self.assertEqual(info["prefix"], sys.prefix)
        self.assertEqual(info["is_virtualenv"], sys.prefix != sys.base_prefix)
        self.assertIsInstance(info["sys_path"], list)
        self.assertIn("prefix", self.json_of("env", "info"))

    def test_info_rejects_non_python(self):
        missing = self.run_sith("env", "info", os.path.join(self.root, "nope"))
        self.assertEqual(missing.returncode, 1)
        other = self.write("not_python", "")
        self.assertEqual(self.run_sith("env", "info", other).returncode, 1)


if __name__ == "__main__":
    unittest.main()
