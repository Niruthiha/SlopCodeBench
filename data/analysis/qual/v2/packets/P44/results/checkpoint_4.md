# Checkpoint 4 hidden-test results

Outcomes: {'passed': 138, 'failed': 8}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_2.py::test_infer_implicit_none_for_no_return  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::test_infer_none_narrowing_in_if_branch  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::test_infer_bare_return_yields_none  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::test_infer_is_not_none_narrowing_excludes_none  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::test_circular_import_hides_name_not_yet_defined  [still failing since ck3]

## .evaluation_tests/test_checkpoint_4.py::test_goto_prefers_py_source_when_stub_exists  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_goto_prefers_py_source_wh0')

    @pytest.mark.functionality
    def test_goto_prefers_py_source_when_stub_exists(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        write_files(
            tmp_path,
            {
                "util.py": "def work():\n    return 1\n",
                "util.pyi": "def work() -> int: ...\n",
            },
        )
        result = run_goto(
            entrypoint_argv,
            tmp_path,
            "main.py",
            "from util import work\nwork|()\n",
        )
        assert result.returncode == 0, result.stderr
        definitions = _field(parse_json_result(result), "definitions")
>       assert definitions[0]["module_path"] == "util.py"
E       AssertionError: assert 'main.py' == 'util.py'
E         
E         - util.py
E         + main.py

.evaluation_tests/test_checkpoint_4.py:504: AssertionError
```

## .evaluation_tests/test_checkpoint_4.py::test_goto_uses_stub_when_definition_only_in_stub  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_goto_uses_stub_when_defin0')

    @pytest.mark.functionality
    def test_goto_uses_stub_when_definition_only_in_stub(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        write_files(
            tmp_path,
            {
                "stubs/only_stub.pyi": "def marker() -> int: ...\n",
            },
        )
        result = run_goto(
            entrypoint_argv,
            tmp_path,
            "main.py",
            "from only_stub import marker\nmarker|()\n",
        )
        assert result.returncode == 0, result.stderr
        definitions = _field(parse_json_result(result), "definitions")
>       assert any(d["module_path"].endswith("only_stub.pyi") for d in definitions)
E       assert False
E        +  where False = any(<generator object test_goto_uses_stub_when_definition_only_in_stub.<locals>.<genexpr> at 0x774be30fcba0>)

.evaluation_tests/test_checkpoint_4.py:525: AssertionError
```

## .evaluation_tests/test_checkpoint_4.py::test_references_unresolved_name_returns_empty  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_references_unresolved_nam0')

    @pytest.mark.error
    def test_references_unresolved_name_returns_empty(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        result = run_references(
            entrypoint_argv,
            tmp_path,
            "main.py",
            "unknown|\n",
            scope="project",
        )
        assert result.returncode == 0, result.stderr
>       assert _field(parse_json_result(result), "references") == []
E       AssertionError: assert [{'module_path': 'main.py', 'line': 1, 'column': 0, 'is_definition': False}] == []
E         
E         Left contains one more item: {'module_path': 'main.py', 'line': 1, 'column': 0, 'is_definition': False}
E         
E         Full diff: (-: missing in left side, +: extra in left side)
E         - []
E         + [
E         +     {
E         +         'module_path': 'main.py',
E         +         'line': 1,
E         +         'column': 0,
E         +         'is_definition': False,
E         +     },
E         + ]

.evaluation_tests/test_checkpoint_4.py:1004: AssertionError
```
