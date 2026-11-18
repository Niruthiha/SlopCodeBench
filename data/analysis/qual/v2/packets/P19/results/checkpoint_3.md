# Checkpoint 3 hidden-test results

Outcomes: {'passed': 162, 'failed': 2}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_3.py::test_checkpoint_3_hidden[04_many_files]  [FIRST]
```
entrypoint_argv = ['uv', 'run', 'mtl.py']
case_dir = PosixPath('/workspace/.evaluation_tests/assets/checkpoint_3_hidden/04_many_files')
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_checkpoint_3_hidden_04_ma0')

    @pytest.mark.functionality
    @pytest.mark.parametrize(
        "case_dir",
        HIDDEN_CASES,
        ids=[case_dir.name for case_dir in HIDDEN_CASES],
    )
    def test_checkpoint_3_hidden(
        entrypoint_argv: list[str],
        case_dir: Path,
        tmp_path: Path,
    ) -> None:
>       run_case(case_dir, "hidden", entrypoint_argv, tmp_path)

.evaluation_tests/test_checkpoint_3.py:94: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/case_utils.py:250: in run_case
    assert_json_equal(actual_output, expected_output)
.evaluation_tests/case_utils.py:169: in assert_json_equal
    assert_json_equal(actual[key], expected_value)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

actual = 9, expected = 10

    def assert_json_equal(actual: Any, expected: Any) -> None:
        if isinstance(expected, dict):
            assert isinstance(actual, dict)
            assert actual.keys() == expected.keys()
            for key, expected_value in expected.items():
                assert_json_equal(actual[key], expected_value)
            return
        if isinstance(expected, list):
            assert isinstance(actual, list)
            assert len(actual) == len(expected)
            for actual_value, expected_value in zip(actual, expected):
                assert_json_equal(actual_value, expected_value)
            return
        if isinstance(expected, bool) or isinstance(actual, bool):
            assert actual == expected
            return
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
>           assert math.isclose(
                actual,
                expected,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
E           AssertionError

.evaluation_tests/case_utils.py:181: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::test_checkpoint_3_edge_format_auto_ambiguous  [FIRST]
```
entrypoint_argv = ['uv', 'run', 'mtl.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_checkpoint_3_edge_format_0')

    @pytest.mark.error
    def test_checkpoint_3_edge_format_auto_ambiguous(
        entrypoint_argv: list[str],
        tmp_path: Path,
    ) -> None:
        (tmp_path / "input").write_text(BASIC_CSV, encoding="utf-8")
        (tmp_path / "pipeline.mtl").write_text(BASIC_DSL, encoding="utf-8")
        args = ["--input", "input", "--dsl", "pipeline.mtl"]
        result = run_command(entrypoint_argv, args, cwd=tmp_path)
>       assert result.returncode == 3
E       assert 0 == 3
E        +  where 0 = CompletedProcess(args=['uv', 'run', '/workspace/mtl.py', '--input', 'input', '--dsl', 'pipeline.mtl'], returncode=0, stdout='{\n  "n": 2,\n  "total": 3.0\n}\n', stderr='').returncode

.evaluation_tests/test_checkpoint_3.py:189: AssertionError
```
