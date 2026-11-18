# Checkpoint 2 hidden-test results

Outcomes: {'passed': 67, 'failed': 4}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_missing_error  [still failing since ck1]

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_empty_value_is_rejected  [still failing since ck1]

## .evaluation_tests/test_checkpoint_2.py::TestCore::test_config_runtime_overrides_project  [FIRST]
```
self = <test_checkpoint_2.TestCore object at 0x70654ed66b70>
cli = <function cli.<locals>._run at 0x70654de40400>
write_config = <function write_config.<locals>._write at 0x70654de41080>

    def test_config_runtime_overrides_project(self, cli, write_config):
        """Runtime ``--color=auto`` overrides project ``color: true``.
    
        Spec: Example 1 – "The resolved value of color is auto."
        """
        write_config({"color": True}, kind="project")
        result = cli(["--color=auto", "help"])
>       assert_success(result)

.evaluation_tests/test_checkpoint_2.py:55: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', '--color=auto', 'help'], returncode=1, stdout='', stderr='Error: The --color global parameter does not accept a value.\n')
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
E         stderr: 'Error: The --color global parameter does not accept a value.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', '--color=auto', 'help'], returncode=1, stdout='', stderr='Error: The --color global parameter does not accept a value.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command  [FIRST]
```
self = <test_checkpoint_2.TestFunctionality object at 0x70654ec11190>
cli = <function cli.<locals>._run at 0x70654de42480>
write_config = <function write_config.<locals>._write at 0x70654de41b20>
fake_ssh_env = ({'PATH': '/tmp/pytest-of-agent/pytest-0/test_ssh_pre_cmd_injected_befo0/fake_ssh_bin:/tmp/uv-cache/archive-v0/T4PKrce...usr/local/games:/usr/games'}, PosixPath('/tmp/pytest-of-agent/pytest-0/test_ssh_pre_cmd_injected_befo0/ssh_calls.log'))

    @pytest.mark.functionality
    def test_ssh_pre_cmd_injected_before_remote_command(
        self, cli, write_config, fake_ssh_env
    ):
        """``APPCTL_SSH_PRE_CMD`` prefixes the remote command payload.
    
        Spec: "``APPCTL_SSH_PRE_CMD`` injects a shell command that runs
        before the main remote command."
        """
        ssh_env, log_file = fake_ssh_env
        write_config(
            {"@remote": {"ssh": "ssh://user@host"}},
            kind="global",
        )
    
        result = cli(
            ["@remote", "site", "list"],
            env={**ssh_env, "APPCTL_SSH_PRE_CMD": "echo prepare"},
        )
    
        assert_success(result)
        calls = log_file.read_text()
>       assert "echo prepare && appctl site list" in calls
E       AssertionError: assert 'echo prepare && appctl site list' in '-T -q user@host echo prepare; appctl site list\n'

.evaluation_tests/test_checkpoint_2.py:600: AssertionError
```
