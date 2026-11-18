# Checkpoint 3 hidden-test results

Outcomes: {'passed': 103, 'failed': 5}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_2.py::test_infer_implicit_none_for_no_return  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::test_infer_none_narrowing_in_if_branch  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::test_infer_bare_return_yields_none  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::test_infer_is_not_none_narrowing_excludes_none  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::test_circular_import_hides_name_not_yet_defined  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_circular_import_hides_nam0')

    @pytest.mark.functionality
    def test_circular_import_hides_name_not_yet_defined(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        write_files(
            tmp_path,
            {
                "a.py": "from b import early\nlate = 1\n",
                "b.py": "from a import late\nearly = 2\n",
            },
        )
        result = run_project_infer(
            entrypoint_argv,
            tmp_path,
            "main.py",
            "from b import late\nlate|\n",
        )
        assert result.returncode == 0, result.stderr
>       assert _defs(result) == []
E       AssertionError: assert [{'name': 'int', 'type': 'instance', 'full_name': 'builtins.int', 'module_path': '', 'line': 0, 'column': 0, 'description': 'instance of int', 'docstring': ''}] == []
E         
E         Left contains one more item: {'name': 'int', 'type': 'instance', 'full_name': 'builtins.int', 'module_path': '', ...}
E         
E         Full diff: (-: missing in left side, +: extra in left side)
E         - []
E         + [
E         +     {
E         +         'name': 'int',
E         +         'type': 'instance',
E         +         'full_name': 'builtins.int',
E         +         'module_path': '',
E         +         'line': 0,
E         +         'column': 0,
E         +         'description': 'instance of int',
E         +         'docstring': '',
E         +     },
E         + ]

.evaluation_tests/test_checkpoint_3.py:669: AssertionError
```
