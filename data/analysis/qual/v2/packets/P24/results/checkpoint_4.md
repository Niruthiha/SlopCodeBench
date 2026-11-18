# Checkpoint 4 hidden-test results

Outcomes: {'passed': 119, 'failed': 14}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_missing_error  [still failing since ck1]

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_empty_value_is_rejected  [still failing since ck1]

## .evaluation_tests/test_checkpoint_2.py::TestCore::test_config_runtime_overrides_project  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_strict_args_mode  [still failing since ck3, REGRESSION]

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::TestErrors::test_invalid_json_stdin_error  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_csv_serializes_complex_values_as_json_strings  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_file_logging_separator_per_invocation  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_json_stdin_supplies_missing_positional_argument  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_confirmation_blank_response_cancels  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_quiet_suppresses_cancellation_warning  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_quiet_does_not_suppress_debug_output  [still failing since ck3]

## .evaluation_tests/test_checkpoint_4.py::TestCore::test_detailed_execution_captures_all_fields  [FIRST]
```
self = <test_checkpoint_4.TestCore object at 0x7eddd4d36a80>
cli = <function cli.<locals>._run at 0x7eddd48f5800>

    def test_detailed_execution_captures_all_fields(self, cli):
        """External command returns stdout, stderr, return_code, run_time.
    
        Spec: "captures a structured result containing: stdout, stderr,
        return_code, run_time."
        """
        result = cli(["--debug", "help"])
        assert_success(result)
        debug = strip_ansi(result.stderr).lower()
        assert "command" in debug
>       assert "return" in debug
E       assert 'return' in "debug (bootstrap): loaded config file: /tmp/pytest-of-agent/pytest-0/test_detailed_execution_captur0/appctl_root/config/config.yml (0.002s)\ndebug (bootstrap): resolved command 'help' with arguments [] (0.003s)\n"

.evaluation_tests/test_checkpoint_4.py:44: AssertionError
```

## .evaluation_tests/test_checkpoint_4.py::TestErrors::test_exit_code_negative_1_warning  [FIRST]
```
self = <test_checkpoint_4.TestErrors object at 0x7eddd4d35730>
cli = <function cli.<locals>._run at 0x7eddd48f5da0>
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_exit_code_negative_1_warn0')

    @pytest.mark.error
    def test_exit_code_negative_1_warning(self, cli, tmp_path):
        """Process returning -1 emits warning to STDERR.
    
        Spec: "emits a warning to STDERR about signal handling configuration."
        """
        bin_dir = tmp_path / "signal_bin"
        bin_dir.mkdir()
        docker = bin_dir / "docker"
        docker.write_text("#!/usr/bin/env sh\nkill -TERM $$\n")
        docker.chmod(0o755)
        compose = bin_dir / "docker-compose"
        compose.write_text("#!/usr/bin/env sh\nexit 0\n")
        compose.chmod(0o755)
        env = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
        result = cli(["site", "list"], env=env)
>       assert "Warning" in result.stderr
E       AssertionError: assert 'Warning' in ''
E        +  where '' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=0, stdout='name  type      title         status\nmain  standard  Main Site     active\nblog  blog      Company Blog  active\nshop  store     Shop          archived\n', stderr='').stderr

.evaluation_tests/test_checkpoint_4.py:172: AssertionError
```
