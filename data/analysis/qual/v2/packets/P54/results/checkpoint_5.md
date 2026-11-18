# Checkpoint 5 hidden-test results

Outcomes: {'passed': 179, 'failed': 7}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_2.py::test_infer_is_not_none_narrowing_excludes_none  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::test_circular_import_hides_name_not_yet_defined  [still failing since ck3]

## .evaluation_tests/test_checkpoint_4.py::test_goto_prefers_py_source_when_stub_exists  [still failing since ck4]

## .evaluation_tests/test_checkpoint_4.py::test_goto_uses_stub_when_definition_only_in_stub  [still failing since ck4]

## .evaluation_tests/test_checkpoint_4.py::test_references_unresolved_name_returns_empty  [still failing since ck4]

## .evaluation_tests/test_checkpoint_5.py::test_extract_variable_inserts_assignment_and_replaces_expression  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_extract_variable_inserts_0')

    def test_extract_variable_inserts_assignment_and_replaces_expression(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        result = run_extract_variable(
            entrypoint_argv,
            tmp_path,
            "main.py",
            ("def lerp(a, b, t):\n    return a + <<b - a>> * t\n"),
            name="delta",
        )
>       assert result.returncode == 0, result.stderr
E       AssertionError: error: selection is not a complete expression
E         
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['uv', 'run', '--project', '/workspace', '/workspace/sith.py', 'extract-variable', '/tmp/pytest-of-agent/pytest-0/test_extract_variable_inserts_0/main.py', '2', '15', '--until', '2:20', '--name', 'delta', '--project', '/tmp/pytest-of-agent/pytest-0/test_extract_variable_inserts_0'], returncode=1, stdout='', stderr='error: selection is not a complete expression\n').returncode

.evaluation_tests/test_checkpoint_5.py:231: AssertionError
```

## .evaluation_tests/test_checkpoint_5.py::test_extract_variable_diff_output_is_unified_diff  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_extract_variable_diff_out0')

    @pytest.mark.functionality
    def test_extract_variable_diff_output_is_unified_diff(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        result = run_extract_variable(
            entrypoint_argv,
            tmp_path,
            "main.py",
            "def lerp(a, b, t):\n    return a + <<b - a>> * t\n",
            name="delta",
            diff=True,
        )
>       assert result.returncode == 0, result.stderr
E       AssertionError: error: selection is not a complete expression
E         
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['uv', 'run', '--project', '/workspace', '/workspace/sith.py', 'extract-variable', '/tmp/pytest-of-agent/pytest-0/test_extract_variable_diff_out0/main.py', '2', '15', '--until', '2:20', '--name', 'delta', '--project', '/tmp/pytest-of-agent/pytest-0/test_extract_variable_diff_out0', '--diff'], returncode=1, stdout='', stderr='error: selection is not a complete expression\n').returncode

.evaluation_tests/test_checkpoint_5.py:714: AssertionError
```
