# Checkpoint 2 hidden-test results

Outcomes: {'passed': 66, 'failed': 5}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_missing_error  [still failing since ck1]

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_empty_value_is_rejected  [still failing since ck1]

## .evaluation_tests/test_checkpoint_2.py::TestErrors::test_unknown_alias_error  [FIRST]
```
self = <test_checkpoint_2.TestErrors object at 0x785afc0e33b0>
cli = <function cli.<locals>._run at 0x785afb30d4e0>
write_config = <function write_config.<locals>._write at 0x785afb30c540>

    @pytest.mark.error
    def test_unknown_alias_error(self, cli, write_config):
        """``@nonexistent`` → error to STDERR, exit 1.
    
        Spec: "Error: Alias '@nonexistent' not found."
        """
        write_config({}, kind="global")
        result = cli(["@nonexistent", "site", "list"])
        assert_exit_code(result, 1)
>       assert "not found" in result.stderr.lower()
E       assert 'not found' in 'error: unable to parse the config file \'/tmp/pytest-of-agent/pytest-0/test_unknown_alias_error0/appctl_root/config/config.yml\': expected \'<document start>\', but found \'<block mapping start>\'\n  in "<unicode string>", line 2, column 1:\n    locale: en_us\n    ^\n'
E        +  where 'error: unable to parse the config file \'/tmp/pytest-of-agent/pytest-0/test_unknown_alias_error0/appctl_root/config/config.yml\': expected \'<document start>\', but found \'<block mapping start>\'\n  in "<unicode string>", line 2, column 1:\n    locale: en_us\n    ^\n' = <built-in method lower of str object at 0x785afb65ec20>()
E        +    where <built-in method lower of str object at 0x785afb65ec20> = 'Error: Unable to parse the config file \'/tmp/pytest-of-agent/pytest-0/test_unknown_alias_error0/appctl_root/config/config.yml\': expected \'<document start>\', but found \'<block mapping start>\'\n  in "<unicode string>", line 2, column 1:\n    locale: en_US\n    ^\n'.lower
E        +      where 'Error: Unable to parse the config file \'/tmp/pytest-of-agent/pytest-0/test_unknown_alias_error0/appctl_root/config/config.yml\': expected \'<document start>\', but found \'<block mapping start>\'\n  in "<unicode string>", line 2, column 1:\n    locale: en_US\n    ^\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', '@nonexistent', 'site', 'list'], returncode=1, stdout='', stderr='Error: Unable to parse the config file \'/tmp/pytest-of-agent/pytest-0/test_unknown_alias_error0/appctl_root/config/config.yml\': expected \'<document start>\', but found \'<block mapping start>\'\n  in "<unicode string>", line 2, column 1:\n    locale: en_US\n    ^\n').stderr

.evaluation_tests/test_checkpoint_2.py:188: AssertionError
```

## .evaluation_tests/test_checkpoint_2.py::TestErrors::test_all_no_aliases_error  [FIRST]
```
lumn 1:\n    locale: en_us\n    ^\n' or '@all' in 'Error: Unable to parse the config file \'/tmp/pytest-of-agent/pytest-0/test_all_no_aliases_error0/appctl_root/config/config.yml\': expected \'<document start>\', but found \'<block mapping start>\'\n  in "<unicode string>", line 2, column 1:\n    locale: en_US\n    ^\n')
E        +  where 'error: unable to parse the config file \'/tmp/pytest-of-agent/pytest-0/test_all_no_aliases_error0/appctl_root/config/config.yml\': expected \'<document start>\', but found \'<block mapping start>\'\n  in "<unicode string>", line 2, column 1:\n    locale: en_us\n    ^\n' = <built-in method lower of str object at 0x785afb65f0e0>()
E        +    where <built-in method lower of str object at 0x785afb65f0e0> = 'Error: Unable to parse the config file \'/tmp/pytest-of-agent/pytest-0/test_all_no_aliases_error0/appctl_root/config/config.yml\': expected \'<document start>\', but found \'<block mapping start>\'\n  in "<unicode string>", line 2, column 1:\n    locale: en_US\n    ^\n'.lower
E        +      where 'Error: Unable to parse the config file \'/tmp/pytest-of-agent/pytest-0/test_all_no_aliases_error0/appctl_root/config/config.yml\': expected \'<document start>\', but found \'<block mapping start>\'\n  in "<unicode string>", line 2, column 1:\n    locale: en_US\n    ^\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', '@all', 'site', 'list'], returncode=1, stdout='', stderr='Error: Unable to parse the config file \'/tmp/pytest-of-agent/pytest-0/test_all_no_aliases_error0/appctl_root/config/config.yml\': expected \'<document start>\', but found \'<block mapping start>\'\n  in "<unicode string>", line 2, column 1:\n    locale: en_US\n    ^\n').stderr
E        +  and   'Error: Unable to parse the config file \'/tmp/pytest-of-agent/pytest-0/test_all_no_aliases_error0/appctl_root/config/config.yml\': expected \'<document start>\', but found \'<block mapping start>\'\n  in "<unicode string>", line 2, column 1:\n    locale: en_US\n    ^\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', '@all', 'site', 'list'], returncode=1, stdout='', stderr='Error: Unable to parse the config file \'/tmp/pytest-of-agent/pytest-0/test_all_no_aliases_error0/appctl_root/config/config.yml\': expected \'<document start>\', but found \'<block mapping start>\'\n  in "<unicode string>", line 2, column 1:\n    locale: en_US\n    ^\n').stderr

.evaluation_tests/test_checkpoint_2.py:213: AssertionError
```

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command  [FIRST]
```
self = <test_checkpoint_2.TestFunctionality object at 0x785afc0deb10>
cli = <function cli.<locals>._run at 0x785afb30e5c0>
write_config = <function write_config.<locals>._write at 0x785afb30dc60>
fake_ssh_env = ({'PATH': '/tmp/pytest-of-agent/pytest-0/test_ssh_pre_cmd_injected_befo0/fake_ssh_bin:/tmp/uv-cache/archive-v0/_BlofF4...usr/local/games:/usr/games'}, PosixPath('/tmp/pytest-of-agent/pytest-0/test_ssh_pre_cmd_injected_befo0/ssh_calls.log'))

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
E       AssertionError: assert 'echo prepare && appctl site list' in '-q -T user@host echo prepare; appctl site list\n'

.evaluation_tests/test_checkpoint_2.py:600: AssertionError
```
