# Checkpoint 2 hidden-test results

Outcomes: {'passed': 68, 'failed': 3}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_missing_error  [still failing since ck1]

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_empty_value_is_rejected  [still failing since ck1]

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command  [FIRST]
```
self = <test_checkpoint_2.TestFunctionality object at 0x7f7139e71370>
cli = <function cli.<locals>._run at 0x7f713908a160>
write_config = <function write_config.<locals>._write at 0x7f7139089d00>
fake_ssh_env = ({'PATH': '/tmp/pytest-of-agent/pytest-0/test_ssh_pre_cmd_injected_befo0/fake_ssh_bin:/tmp/uv-cache/archive-v0/6BkAXMf...usr/local/games:/usr/games'}, PosixPath('/tmp/pytest-of-agent/pytest-0/test_ssh_pre_cmd_injected_befo0/ssh_calls.log'))

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
E       assert 'echo prepare && appctl site list' in "-T -q user@host echo prepare; appctl 'site' 'list'\n"

.evaluation_tests/test_checkpoint_2.py:600: AssertionError
```
