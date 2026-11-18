# Checkpoint 4 hidden-test results

Outcomes: {'skipped': 46, 'passed': 176, 'failed': 4}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_3.py::test_checkpoint_3_hidden[04_many_files]  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::test_checkpoint_3_edge_format_auto_ambiguous  [still failing since ck3]

## .evaluation_tests/test_checkpoint_4.py::test_checkpoint_4_hidden[05_join_full_outer]  [FIRST]
```
entrypoint_argv = ['uv', 'run', 'mtl.py']
case_dir = PosixPath('/workspace/.evaluation_tests/assets/checkpoint_4_hidden/05_join_full_outer')
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_checkpoint_4_hidden_05_jo0')

    @pytest.mark.functionality
    @pytest.mark.parametrize(
        "case_dir",
        HIDDEN_CASES,
        ids=[case_dir.name for case_dir in HIDDEN_CASES],
    )
    def test_checkpoint_4_hidden(
        entrypoint_argv: list[str],
        case_dir: Path,
        tmp_path: Path,
    ) -> None:
>       run_case(case_dir, "hidden", entrypoint_argv, tmp_path)

.evaluation_tests/test_checkpoint_4.py:96: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/case_utils.py:250: in run_case
    assert_json_equal(actual_output, expected_output)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

actual = [{'window_start': '2024-01-01T10:00:00Z', 'window_end': '2024-01-01T11:00:00Z', 'location': 'NYC', 'item': 'apple', .....window_start': '2024-01-01T10:00:00Z', 'window_end': '2024-01-01T11:00:00Z', 'location': 'NYC', 'item': 'banana', ...}]
expected = [{'window_start': '2024-01-01T10:00:00Z', 'window_end': '2024-01-01T11:00:00Z', 'location': None, 'item': None, ...}, ...window_start': '2024-01-01T10:00:00Z', 'window_end': '2024-01-01T11:00:00Z', 'location': 'NYC', 'item': 'banana', ...}]

    def assert_json_equal(actual: Any, expected: Any) -> None:
        if isinstance(expected, dict):
            assert isinstance(actual, dict)
            assert actual.keys() == expected.keys()
            for key, expected_value in expected.items():
                assert_json_equal(actual[key], expected_value)
            return
        if isinstance(expected, list):
            assert isinstance(actual, list)
>           assert len(actual) == len(expected)
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E           AssertionError

.evaluation_tests/case_utils.py:173: AssertionError
```

## .evaluation_tests/test_checkpoint_4.py::test_checkpoint_4_regression[33_recursive_directory]  [FIRST]
```
entrypoint_argv = ['uv', 'run', 'mtl.py']
case_dir = PosixPath('/workspace/.evaluation_tests/assets/checkpoint_4_regression/33_recursive_directory')
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_checkpoint_4_regression_33')

    @pytest.mark.functionality
    @pytest.mark.parametrize(
        "case_dir",
        REGRESSION_CASES,
        ids=[case_dir.name for case_dir in REGRESSION_CASES],
    )
    def test_checkpoint_4_regression(
        entrypoint_argv: list[str],
        case_dir: Path,
        tmp_path: Path,
    ) -> None:
>       run_case(case_dir, "regression", entrypoint_argv, tmp_path)

.evaluation_tests/test_checkpoint_4.py:110: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/case_utils.py:250: in run_case
    assert_json_equal(actual_output, expected_output)
.evaluation_tests/case_utils.py:169: in assert_json_equal
    assert_json_equal(actual[key], expected_value)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

actual = 2, expected = 3

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
