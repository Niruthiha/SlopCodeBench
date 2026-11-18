# Checkpoint 1 hidden-test results

Outcomes: {'passed': 32, 'failed': 2}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_missing_error  [FIRST]
```
self = <test_checkpoint_1.TestFunctionality object at 0x777e17be06e0>
cli = <function cli.<locals>._run at 0x777e1717fe20>

    @pytest.mark.functionality
    def test_required_associative_missing_error(self, cli):
        """Missing required ``--type=<type>`` → error.
    
        Spec: Error Summary table.
        """
        result = cli(["site", "create", "example.test"])
>       assert_exit_code(result, 1)

.evaluation_tests/test_checkpoint_1.py:406: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test'], returncode=0, stdout="Success: Created site 'example.test' (type: standard, title: example.test).\n", stderr='')
code = 1

    def assert_exit_code(
        result: subprocess.CompletedProcess[str], code: int
    ) -> None:
        """Assert the process exited with *code*."""
>       assert result.returncode == code, (
            f"Expected exit code {code}, got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
E       AssertionError: Expected exit code 1, got 0.
E         stdout: "Success: Created site 'example.test' (type: standard, title: example.test).\n"
E         stderr: ''
E       assert 0 == 1
E        +  where 0 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test'], returncode=0, stdout="Success: Created site 'example.test' (type: standard, title: example.test).\n", stderr='').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_empty_value_is_rejected  [FIRST]
```
self = <test_checkpoint_1.TestFunctionality object at 0x777e17d95070>
cli = <function cli.<locals>._run at 0x777e16ea49a0>

    @pytest.mark.functionality
    def test_required_associative_empty_value_is_rejected(self, cli):
        """Required associative args must have non-empty values.
    
        Spec: "All required associative arguments must be present with
        non-empty values."
        """
        result = cli(["site", "create", "example.test", "--type="])
>       assert_exit_code(result, 1)

.evaluation_tests/test_checkpoint_1.py:420: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test', '--type='], returncode=0, stdout="Success: Created site 'example.test' (type: , title: example.test).\n", stderr='')
code = 1

    def assert_exit_code(
        result: subprocess.CompletedProcess[str], code: int
    ) -> None:
        """Assert the process exited with *code*."""
>       assert result.returncode == code, (
            f"Expected exit code {code}, got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
E       AssertionError: Expected exit code 1, got 0.
E         stdout: "Success: Created site 'example.test' (type: , title: example.test).\n"
E         stderr: ''
E       assert 0 == 1
E        +  where 0 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test', '--type='], returncode=0, stdout="Success: Created site 'example.test' (type: , title: example.test).\n", stderr='').returncode

.evaluation_tests/conftest.py:314: AssertionError
```
