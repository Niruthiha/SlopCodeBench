# Checkpoint 3 hidden-test results

Outcomes: {'passed': 97, 'failed': 8}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_missing_error  [still failing since ck1]

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_empty_value_is_rejected  [still failing since ck1]

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::TestErrors::test_invalid_json_stdin_error  [FIRST]
```
self = <test_checkpoint_3.TestErrors object at 0x7e97a9ed0050>
cli = <function cli.<locals>._run at 0x7e97a9162840>

    @pytest.mark.error
    def test_invalid_json_stdin_error(self, cli):
        """Invalid JSON on STDIN with ``--format=json`` → error.
    
        Spec: "Error: Invalid JSON: <raw_input>."
        """
        result = cli(
            ["site", "create", "--format=json"],
            input_text="not valid json{{{",
        )
        assert_exit_code(result, 1)
>       assert "Error: Invalid JSON:" in result.stderr
E       AssertionError: assert 'Error: Invalid JSON:' in '+----------------------------+\n| Error: Parameter errors:   |\n| unknown --format parameter |\n+----------------------------+\n'
E        +  where '+----------------------------+\n| Error: Parameter errors:   |\n| unknown --format parameter |\n+----------------------------+\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', '--format=json'], returncode=1, stdout='', stderr='+----------------------------+\n| Error: Parameter errors:   |\n| unknown --format parameter |\n+----------------------------+\n').stderr

.evaluation_tests/test_checkpoint_3.py:135: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_csv_serializes_complex_values_as_json_strings  [FIRST]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e97a9ed5b80>
cli = <function cli.<locals>._run at 0x7e97a9162c00>

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
li.<locals>._run at 0x7e97a9163240>
fake_docker_env = ({'PATH': '/tmp/pytest-of-agent/pytest-0/test_json_stdin_supplies_missi0/fake_docker_bin:/tmp/uv-cache/archive-v0/nGBT.../local/games:/usr/games'}, PosixPath('/tmp/pytest-of-agent/pytest-0/test_json_stdin_supplies_missi0/docker_calls.log'))

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', '--type=html', '--format=...------------------+\n| Error: Parameter errors:   |\n| unknown --format parameter |\n+----------------------------+\n')
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
E         stderr: '+----------------------------+\n| Error: Parameter errors:   |\n| unknown --format parameter |\n+----------------------------+\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', '--type=html', '--format=json'], returncode=1, stdout='', stderr='+----------------------------+\n| Error: Parameter errors:   |\n| unknown --format parameter |\n+----------------------------+\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_confirmation_blank_response_cancels  [FIRST]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e97a9ed66f0>
cli = <function cli.<locals>._run at 0x7e97a9163100>

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
>       assert_exit_code(result, 1)

.evaluation_tests/test_checkpoint_3.py:452: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returnco..., stdout="Are you sure you want to delete the 'example.test' site? [y/n] \n", stderr='Warning: Operation cancelled.\n')
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
E         stdout: "Are you sure you want to delete the 'example.test' site? [y/n] \n"
E         stderr: 'Warning: Operation cancelled.\n'
E       assert 0 == 1
E        +  where 0 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=0, stdout="Are you sure you want to delete the 'example.test' site? [y/n] \n", stderr='Warning: Operation cancelled.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_quiet_suppresses_cancellation_warning  [FIRST]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e97a953e300>
cli = <function cli.<locals>._run at 0x7e97a9162b60>

    @pytest.mark.functionality
    def test_quiet_suppresses_cancellation_warning(self, cli):
        """Quiet mode still aborts cancellation paths with the same exit code.
    
        Spec: cancellation remains an error-path return while quiet mode
        suppresses regular informational/success chatter.
        """
        result = cli(
            ["--quiet", "site", "delete", "example.test"],
            input_text="n\n",
        )
>       assert_exit_code(result, 1)

.evaluation_tests/test_checkpoint_3.py:466: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', '--quiet', 'site', 'delete', 'example.test'..., stdout="Are you sure you want to delete the 'example.test' site? [y/n] \n", stderr='Warning: Operation cancelled.\n')
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
E         stdout: "Are you sure you want to delete the 'example.test' site? [y/n] \n"
E         stderr: 'Warning: Operation cancelled.\n'
E       assert 0 == 1
E        +  where 0 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', '--quiet', 'site', 'delete', 'example.test'], returncode=0, stdout="Are you sure you want to delete the 'example.test' site? [y/n] \n", stderr='Warning: Operation cancelled.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```
