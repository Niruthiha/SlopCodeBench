# Checkpoint 1 hidden-test results

Outcomes: {'passed': 32, 'failed': 2}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_missing_error  [FIRST]
```
self = <test_checkpoint_1.TestFunctionality object at 0x7e9af6de0bc0>
cli = <function cli.<locals>._run at 0x7e9af637be20>

    @pytest.mark.functionality
    def test_required_associative_missing_error(self, cli):
        """Missing required ``--type=<type>`` → error.
    
        Spec: Error Summary table.
        """
        result = cli(["site", "create", "example.test"])
        assert_exit_code(result, 1)
>       assert (
            "Parameter errors" in result.stderr
            or "usage:" in result.stdout.lower()
        )
E       assert ('Parameter errors' in "Error: Invalid site name 'example.test'. Use lowercase letters, numbers and hyphens only.\n" or 'usage:' in '')
E        +  where "Error: Invalid site name 'example.test'. Use lowercase letters, numbers and hyphens only.\n" = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test'], returncode=1, stdout='', stderr="Error: Invalid site name 'example.test'. Use lowercase letters, numbers and hyphens only.\n").stderr
E        +  and   '' = <built-in method lower of str object at 0x7e9af85b6290>()
E        +    where <built-in method lower of str object at 0x7e9af85b6290> = ''.lower
E        +      where '' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test'], returncode=1, stdout='', stderr="Error: Invalid site name 'example.test'. Use lowercase letters, numbers and hyphens only.\n").stdout

.evaluation_tests/test_checkpoint_1.py:407: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_empty_value_is_rejected  [FIRST]
```
self = <test_checkpoint_1.TestFunctionality object at 0x7e9af6f47230>
cli = <function cli.<locals>._run at 0x7e9af6144a40>

    @pytest.mark.functionality
    def test_required_associative_empty_value_is_rejected(self, cli):
        """Required associative args must have non-empty values.
    
        Spec: "All required associative arguments must be present with
        non-empty values."
        """
        result = cli(["site", "create", "example.test", "--type="])
        assert_exit_code(result, 1)
>       assert_stderr_contains(
            result,
            "Error: Parameter errors:",
            "missing --type parameter",
        )

.evaluation_tests/test_checkpoint_1.py:421: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test', '--type='...ode=1, stdout='', stderr="Error: Invalid site name 'example.test'. Use lowercase letters, numbers and hyphens only.\n")
fragments = ('Error: Parameter errors:', 'missing --type parameter')

    def assert_stderr_contains(
        result: subprocess.CompletedProcess[str], *fragments: str
    ) -> None:
        """Assert all *fragments* appear in stderr."""
        for frag in fragments:
>           assert frag in result.stderr, (
                f"Missing {frag!r} in stderr.\nstderr: {result.stderr!r}"
            )
E           AssertionError: Missing 'Error: Parameter errors:' in stderr.
E             stderr: "Error: Invalid site name 'example.test'. Use lowercase letters, numbers and hyphens only.\n"
E           assert 'Error: Parameter errors:' in "Error: Invalid site name 'example.test'. Use lowercase letters, numbers and hyphens only.\n"
E            +  where "Error: Invalid site name 'example.test'. Use lowercase letters, numbers and hyphens only.\n" = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test', '--type='], returncode=1, stdout='', stderr="Error: Invalid site name 'example.test'. Use lowercase letters, numbers and hyphens only.\n").stderr

.evaluation_tests/conftest.py:344: AssertionError
```
