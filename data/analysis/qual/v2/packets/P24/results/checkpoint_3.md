# Checkpoint 3 hidden-test results

Outcomes: {'passed': 93, 'failed': 12}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_missing_error  [still failing since ck1]

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_empty_value_is_rejected  [still failing since ck1]

## .evaluation_tests/test_checkpoint_2.py::TestCore::test_config_runtime_overrides_project  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_strict_args_mode  [FIRST, REGRESSION]
```
self = <test_checkpoint_2.TestFunctionality object at 0x73f88d49ed80>
cli = <function cli.<locals>._run at 0x73f88c7b5620>

    @pytest.mark.functionality
    def test_strict_args_mode(self, cli):
        """Strict mode treats post-positional args as command-specific.
    
        Spec: "only arguments appearing before the first positional token
        are treated as global runtime configuration flags."
        """
        strict = cli(
            ["site", "list", "--debug"],
            env={"APPCTL_STRICT_ARGS_MODE": "1"},
        )
        non_strict = cli(["site", "list", "--debug"])
        assert "Debug:" not in strict.stderr
>       assert "Debug:" in non_strict.stderr
E       assert 'Debug:' in "Debug (bootstrap): Loaded config file: /tmp/pytest-of-agent/pytest-0/test_strict_args_mode0/appctl_root/config/config.yml (0.001s)\nDebug (bootstrap): Resolved command 'site list' with arguments [] (0.002s)\n"
E        +  where "Debug (bootstrap): Loaded config file: /tmp/pytest-of-agent/pytest-0/test_strict_args_mode0/appctl_root/config/config.yml (0.001s)\nDebug (bootstrap): Resolved command 'site list' with arguments [] (0.002s)\n" = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--debug'], returncode=0, stdout='name  type      title         status\nmain  standard  Main Site     active\nblog  blog      Company Blog  active\nshop  store     Shop          archived\n', stderr="Debug (bootstrap): Loaded config file: /tmp/pytest-of-agent/pytest-0/test_strict_args_mode0/appctl_root/config/config.yml (0.001s)\nDebug (bootstrap): Resolved command 'site list' with arguments [] (0.002s)\n").stderr

.evaluation_tests/test_checkpoint_2.py:457: AssertionError
```

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::TestErrors::test_invalid_json_stdin_error  [FIRST]
```
self = <test_checkpoint_3.TestErrors object at 0x73f88d5e09e0>
cli = <function cli.<locals>._run at 0x73f88c7b5da0>

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
E       AssertionError: assert 'Error: Invalid JSON:' in 'Error: Parameter errors:\n unknown --format parameter\n'
E        +  where 'Error: Parameter errors:\n unknown --format parameter\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', '--format=json'], returncode=1, stdout='', stderr='Error: Parameter errors:\n unknown --format parameter\n').stderr

.evaluation_tests/test_checkpoint_3.py:135: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_csv_serializes_complex_values_as_json_strings  [FIRST]
```
self = <test_checkpoint_3.TestFunctionality object at 0x73f88d49caa0>
cli = <function cli.<locals>._run at 0x73f88c7b6980>

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

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_file_logging_separator_per_invocation  [FIRST]
```
self = <test_checkpoint_3.TestFunctionality object at 0x73f88cc51b80>
cli = <function cli.<locals>._run at 0x73f88c7b6a20>
log_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_file_logging_separator_pe0/appctl_root/logs/appctl.log')

    @pytest.mark.functionality
    def test_file_logging_separator_per_invocation(self, cli, log_path):
        """Each invocation delimited with separator line.
    
        Spec: "Each invocation is delimited with a separator line."
        """
        cli(["help"])
        cli(["help"])
        if log_path.exists():
            content = log_path.read_text()
            # Should have separator lines between invocations
            # EasyEngine uses "::::::::::::::::::::::::ee invoked::::::::::::::::::::::::"
            separator_candidates = [
                l
                for l in content.splitlines()
                if l.strip()
                and set(l.strip()) <= set(":= -_invoked appctl")
                or "invoked" in l.lower()
                or l.startswith("---")
                or l.startswith("===")
            ]
>           assert len(separator_candidates) >= 2
E           assert 0 >= 2
E            +  where 0 = len([])

.evaluation_tests/test_checkpoint_3.py:381: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_json_stdin_supplies_missing_positional_argument  [FIRST]
```
self = <test_checkpoint_3.TestFunctionality object at 0x73f88d5e5eb0>
cli = <function cli.<locals>._run at 0x73f88c7b7100>
fake_docker_env = ({'PATH': '/tmp/pytest-of-agent/pytest-0/test_json_stdin_supplies_missi0/fake_docker_bin:/tmp/uv-cache/archive-v0/S96S.../local/games:/usr/games'}, PosixPath('/tmp/pytest-of-agent/pytest-0/test_json_stdin_supplies_missi0/docker_calls.log'))

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

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_confirmation_blank_response_cancels  [FIRST]
```
self = <test_checkpoint_3.TestFunctionality object at 0x73f88d49f080>
cli = <function cli.<locals>._run at 0x73f88c7b74c0>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=0, stdout="Are you sure you want to delete the site 'example.test'? [y/n] ", stderr='Warning: Operation cancelled.\n')
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
E         stdout: "Are you sure you want to delete the site 'example.test'? [y/n] "
E         stderr: 'Warning: Operation cancelled.\n'
E       assert 0 == 1
E        +  where 0 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=0, stdout="Are you sure you want to delete the site 'example.test'? [y/n] ", stderr='Warning: Operation cancelled.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_quiet_suppresses_cancellation_warning  [FIRST]
```
self = <test_checkpoint_3.TestFunctionality object at 0x73f88cc52330>
cli = <function cli.<locals>._run at 0x73f88c7b7b00>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', '--quiet', 'site', 'delete', 'example.test'...=0, stdout="Are you sure you want to delete the site 'example.test'? [y/n] ", stderr='Warning: Operation cancelled.\n')
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
E         stdout: "Are you sure you want to delete the site 'example.test'? [y/n] "
E         stderr: 'Warning: Operation cancelled.\n'
E       assert 0 == 1
E        +  where 0 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', '--quiet', 'site', 'delete', 'example.test'], returncode=0, stdout="Are you sure you want to delete the site 'example.test'? [y/n] ", stderr='Warning: Operation cancelled.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_quiet_does_not_suppress_debug_output  [FIRST]
```
self = <test_checkpoint_3.TestFunctionality object at 0x73f88cc51d30>
cli = <function cli.<locals>._run at 0x73f88c7b7f60>

    @pytest.mark.functionality
    def test_quiet_does_not_suppress_debug_output(self, cli):
        """``--quiet`` does not suppress debug output.
    
        Spec: "``--quiet`` must suppress informational messages, success
        messages, and warnings." Debug output is enabled separately by
        ``--debug``.
        """
        result = cli(["--quiet", "--debug", "help"])
        assert_success(result)
>       assert "Debug:" in result.stderr
E       assert 'Debug:' in "Debug (bootstrap): Loaded config file: /tmp/pytest-of-agent/pytest-0/test_quiet_does_not_suppress_d0/appctl_root/config/config.yml (0.005s)\nDebug (bootstrap): Resolved command 'help' with arguments [] (0.006s)\n"
E        +  where "Debug (bootstrap): Loaded config file: /tmp/pytest-of-agent/pytest-0/test_quiet_does_not_suppress_d0/appctl_root/config/config.yml (0.005s)\nDebug (bootstrap): Resolved command 'help' with arguments [] (0.006s)\n" = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', '--quiet', '--debug', 'help'], returncode=0, stdout="usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nAvailable commands:\n\n  cache   Adds, removes, fetches, and flushes the object cache.\n  cli     Reviews current appctl info and checks registered commands.\n  config  Generates and reads the configuration file.\n  help    Gets help for appctl commands.\n  option  Retrieves and sets site options.\n  plugin  Manages plugins, including installs, activations, and updates.\n  post    Manages posts, content, and meta.\n  site    Creates, deletes, empties, archives, and lists sites.\n  user    Manages users, along with their roles and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr="Debug (bootstrap): Loaded config file: /tmp/pytest-of-agent/pytest-0/test_quiet_does_not_suppress_d0/appctl_root/config/config.yml (0.005s)\nDebug (bootstrap): Resolved command 'help' with arguments [] (0.006s)\n").stderr

.evaluation_tests/test_checkpoint_3.py:478: AssertionError
```
