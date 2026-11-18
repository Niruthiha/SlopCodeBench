# Checkpoint 3 hidden-test results

Outcomes: {'passed': 95, 'failed': 10}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_missing_error  [still failing since ck1]

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_empty_value_is_rejected  [still failing since ck1]

## .evaluation_tests/test_checkpoint_2.py::TestErrors::test_unknown_alias_error  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::TestErrors::test_all_no_aliases_error  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::TestErrors::test_confirmation_prompt_non_y_aborts  [FIRST]
```
self = <test_checkpoint_3.TestErrors object at 0x7e875d87da00>
cli = <function cli.<locals>._run at 0x7e875d424f40>

    @pytest.mark.error
    def test_confirmation_prompt_non_y_aborts(self, cli):
        """Confirmation prompt with response "n" aborts operation.
    
        Spec: "Any response other than y ... prints
        Warning: Operation cancelled."
        """
        cli(["site", "create", "example.test", "--type=html", "--yes"])
        result = cli(["site", "delete", "example.test"], input_text="n\n")
>       assert "Warning: Operation cancelled." in result.stderr
E       assert 'Warning: Operation cancelled.' in "Error: Site 'example.test' does not exist.\n"
E        +  where "Error: Site 'example.test' does not exist.\n" = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=1, stdout='', stderr="Error: Site 'example.test' does not exist.\n").stderr

.evaluation_tests/test_checkpoint_3.py:146: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_csv_serializes_complex_values_as_json_strings  [FIRST]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e875e0cf260>
cli = <function cli.<locals>._run at 0x7e875d424fe0>

    @pytest.mark.functionality
    def test_csv_serializes_complex_values_as_json_strings(self, cli):
        """Complex values in CSV output are serialized as JSON strings.
    
        Spec: "Complex values such as arrays and objects must be serialized
        as JSON strings when they appear in table or csv output."
        """
        result = cli(["site", "list", "--format=csv", "--fields=tags,meta"])
>       assert_success(result)

.evaluation_tests/test_checkpoint_3.py:204: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=csv', '--fields=tags,meta'], returncode=1, stdout='', stderr='Error: Invalid field: tags.\n')
code = 0

    def assert_exit_code(
        result: subprocess.CompletedProcess[str], code: int
    ) -> None:
        """Assert the process exited with *code*."""
>       assert result.returncode == code, (
            f"Expected exit code {code}, got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
E       AssertionError: Expected exit code 0, got 1.
E         stdout: ''
E         stderr: 'Error: Invalid field: tags.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=csv', '--fields=tags,meta'], returncode=1, stdout='', stderr='Error: Invalid field: tags.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_json_stdin_supplies_missing_positional_argument  [FIRST]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e875e216cf0>
cli = <function cli.<locals>._run at 0x7e875d425bc0>
fake_docker_env = ({'PATH': '/tmp/pytest-of-agent/pytest-0/test_json_stdin_supplies_missi0/fake_docker_bin:/tmp/uv-cache/archive-v0/JSvO.../local/games:/usr/games'}, PosixPath('/tmp/pytest-of-agent/pytest-0/test_json_stdin_supplies_missi0/docker_calls.log'))

    @pytest.mark.functionality
    def test_json_stdin_supplies_missing_positional_argument(
        self, cli, fake_docker_env
    ):
        """Missing positional values are read from STDIN in JSON mode.
    
        Spec: "If a positional argument value is missing from the command
        line, the implementation attempts to read that value from STDIN...
        When --format=json is active, STDIN is parsed as JSON."
        """
        docker_env, _ = fake_docker_env
        result = cli(
            ["site", "create", "--type=html", "--format=json"],
            input_text='{"site-name": "stdin.test"}\n',
            env=docker_env,
        )
>       assert_success(result)

.evaluation_tests/test_checkpoint_3.py:413: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', '--type=html', '--format=json'], returncode=1, stdout='', stderr='Error: Parameter errors:\n unknown --format parameter\n')
code = 0

    def assert_exit_code(
        result: subprocess.CompletedProcess[str], code: int
    ) -> None:
        """Assert the process exited with *code*."""
>       assert result.returncode == code, (
            f"Expected exit code {code}, got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
E       AssertionError: Expected exit code 0, got 1.
E         stdout: ''
E         stderr: 'Error: Parameter errors:\n unknown --format parameter\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', '--type=html', '--format=json'], returncode=1, stdout='', stderr='Error: Parameter errors:\n unknown --format parameter\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_confirmation_accepts_trimmed_uppercase_y  [FIRST]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e875e0cfe60>
cli = <function cli.<locals>._run at 0x7e875d426840>

    @pytest.mark.functionality
    def test_confirmation_accepts_trimmed_uppercase_y(self, cli):
        """Confirmation trims and lowercases input before comparison.
    
        Spec: "read one line from STDIN, lowercase the response, and trim
        surrounding whitespace before returning it."
        """
        result = cli(
            ["site", "delete", "example.test"],
            input_text="  Y  \n",
        )
>       assert_success(result)

.evaluation_tests/test_checkpoint_3.py:438: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=1, stdout='', stderr="Error: Site 'example.test' does not exist.\n")
code = 0

    def assert_exit_code(
        result: subprocess.CompletedProcess[str], code: int
    ) -> None:
        """Assert the process exited with *code*."""
>       assert result.returncode == code, (
            f"Expected exit code {code}, got {result.returncode}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
E       AssertionError: Expected exit code 0, got 1.
E         stdout: ''
E         stderr: "Error: Site 'example.test' does not exist.\n"
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=1, stdout='', stderr="Error: Site 'example.test' does not exist.\n").returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_confirmation_blank_response_cancels  [FIRST]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e875e0cf680>
cli = <function cli.<locals>._run at 0x7e875d426de0>

    @pytest.mark.functionality
    def test_confirmation_blank_response_cancels(self, cli):
        """Blank confirmation input still cancels the operation.
    
        Spec: "Any response other than y, after trimming and case
        normalization, must abort the operation."
        """
        result = cli(
            ["site", "delete", "example.test"],
            input_text="\n",
        )
        assert_exit_code(result, 1)
>       assert "Warning: Operation cancelled." in result.stderr
E       assert 'Warning: Operation cancelled.' in "Error: Site 'example.test' does not exist.\n"
E        +  where "Error: Site 'example.test' does not exist.\n" = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=1, stdout='', stderr="Error: Site 'example.test' does not exist.\n").stderr

.evaluation_tests/test_checkpoint_3.py:453: AssertionError
```
