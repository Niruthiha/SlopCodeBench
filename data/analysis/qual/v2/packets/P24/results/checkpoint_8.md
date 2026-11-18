# Checkpoint 8 hidden-test results

Outcomes: {'passed': 164, 'failed': 90, 'skipped': 1}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_1.py::TestCore::test_help_rewrite  [FIRST, REGRESSION]
```
s, archives, and lists sites.\n\nSYNOPSIS\n\n  appctl site <command>\n\nSUBCOMMANDS\n\n  archive      Archives one or more sites.\n  config       Shows the merged compose configuration of the project.\n  create       Creates a site.\n  delete       Deletes a site.\n  down         Removes the containers, networks and volumes of the project.\n  empty        Empties a site of its content.\n  exec         Runs a command inside a service container.\n  has-service  Detects if a service exists in the project.\n  list         Lists all sites.\n  up           Starts the services of the project in the background.\n  update       Updates fields of a site.' == 'NAME\n\n  appctl site\n\nDESCRIPTION\n\n  Creates, deletes, empties, archives, and lists sites.\n\nSYNOPSIS\n\n  appctl site <command>\n\nSUBCOMMANDS\n\n  archive      Archives one or more sites.\n  config       Shows the merged compose configuration of the project.\n  create       Creates a site.\n  delete       Deletes a site.\n  down         Removes the containers, networks and volumes of the project.\n  empty        Empties a site of its content.\n  exec         Runs a command inside a service container.\n  has-service  Detects if a service exists in the project.\n  list         Lists all sites.\n  up           Starts the services of the project in the background.\n  update       Updates fields of a site.'
E         
E         + Success: AppCtl has been set up successfully.
E           NAME
E           
E             appctl site
E           
E           DESCRIPTION
E           
E             Creates, deletes, empties, archives, and lists sites.
E           
E           SYNOPSIS
E           
E             appctl site <command>
E           
E           SUBCOMMANDS
E           
E             archive      Archives one or more sites.
E             config       Shows the merged compose configuration of the project.
E             create       Creates a site.
E             delete       Deletes a site.
E             down         Removes the containers, networks and volumes of the project.
E             empty        Empties a site of its content.
E             exec         Runs a command inside a service container.
E             has-service  Detects if a service exists in the project.
E             list         Lists all sites.
E             up           Starts the services of the project in the background.
E             update       Updates fields of a site.

.evaluation_tests/test_checkpoint_1.py:89: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestCore::test_help_rewrite_for_multi_level_command  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestCore object at 0x725329a61520>
cli = <function cli.<locals>._run at 0x725328acbf60>

    @pytest.mark.functionality
    def test_help_rewrite_for_multi_level_command(self, cli):
        """``appctl site create --help`` rewrites to ``appctl help site create``.
    
        Spec: command names may be multi-level, and
        "appctl <command> --help" is rewritten before dispatch.
        """
        rewritten = cli(["site", "create", "--help"])
        direct = cli(["help", "site", "create"])
        assert_success(rewritten)
        assert_success(direct)
>       assert (
            strip_ansi(rewritten.stdout).strip()
            == strip_ansi(direct.stdout).strip()
        )
E       AssertionError: assert 'Success: AppCtl has been set up successfully.\nNAME\n\n  appctl site create\n\nDESCRIPTION\n\n  Creates a site.\n\nSYNOPSIS\n\n  appctl site create <site-name> [--type=<type>] [--title=<title>] [--email=<email>] [--private] [--porcelain]\n\nALIAS\n\n  new\n\nDEFAULTS\n\n  --type: standard' == 'NAME\n\n  appctl site create\n\nDESCRIPTION\n\n  Creates a site.\n\nSYNOPSIS\n\n  appctl site create <site-name> [--type=<type>] [--title=<title>] [--email=<email>] [--private] [--porcelain]\n\nALIAS\n\n  new\n\nDEFAULTS\n\n  --type: standard'
E         
E         + Success: AppCtl has been set up successfully.
E           NAME
E           
E             appctl site create
E           
E           DESCRIPTION
E           
E             Creates a site.
E           
E           SYNOPSIS
E           
E             appctl site create <site-name> [--type=<type>] [--title=<title>] [--email=<email>] [--private] [--porcelain]
E           
E           ALIAS
E           
E             new
E           
E           DEFAULTS
E           
E             --type: standard

.evaluation_tests/test_checkpoint_1.py:105: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestErrors::test_missing_required_positional_shows_usage  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestErrors object at 0x7253298fd850>
cli = <function cli.<locals>._run at 0x725328a00540>

    @pytest.mark.error
    def test_missing_required_positional_shows_usage(self, cli):
        """Missing positional prints usage line to STDOUT, exit 1.
    
        Spec: "If not, the tool prints the command's usage line and exits
        with code 1." Example 4.
        """
        result = cli(["site", "create", "--type=html"])
        assert_exit_code(result, 1)
>       assert (
            "usage:" in result.stdout.lower()
            or "usage:" in result.stderr.lower()
        )
E       AssertionError: assert ('usage:' in '' or 'usage:' in 'error: container runtime is not installed or not running. please install and start the container runtime to run appctl.\n')
E        +  where '' = <built-in method lower of str object at 0x72532b0cc290>()
E        +    where <built-in method lower of str object at 0x72532b0cc290> = ''.lower
E        +      where '' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', '--type=html'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').stdout
E        +  and   'error: container runtime is not installed or not running. please install and start the container runtime to run appctl.\n' = <built-in method lower of str object at 0x725328b33730>()
E        +    where <built-in method lower of str object at 0x725328b33730> = 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'.lower
E        +      where 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', '--type=html'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').stderr

.evaluation_tests/test_checkpoint_1.py:159: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestErrors::test_excess_positional_args_error  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestErrors object at 0x7253298fc620>
cli = <function cli.<locals>._run at 0x725328a00a40>

    @pytest.mark.error
    def test_excess_positional_args_error(self, cli):
        """Extra positional args without repeating token → error.
    
        Spec: "Error: Too many positional arguments: extra-arg" Example 6.
        """
        result = cli(["site", "create", "example.test", "extra-arg"])
        assert_exit_code(result, 1)
>       assert "Too many positional arguments" in result.stderr
E       AssertionError: assert 'Too many positional arguments' in 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E        +  where 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test', 'extra-arg'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').stderr

.evaluation_tests/test_checkpoint_1.py:172: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestErrors::test_unknown_associative_with_suggestion  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestErrors object at 0x725329a60dd0>
cli = <function cli.<locals>._run at 0x725328a00ea0>

    @pytest.mark.error
    def test_unknown_associative_with_suggestion(self, cli):
        """Unknown ``--typo`` with registered ``--type`` (dist ≤ 2) → suggestion.
    
        Spec: Example 5.
        """
        result = cli(["site", "create", "example.test", "--typo=html"])
        assert_exit_code(result, 1)
>       assert "Parameter errors" in result.stderr
E       AssertionError: assert 'Parameter errors' in 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E        +  where 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test', '--typo=html'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').stderr

.evaluation_tests/test_checkpoint_1.py:182: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestErrors::test_unknown_associative_no_suggestion  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestErrors object at 0x725329a61280>
cli = <function cli.<locals>._run at 0x725328a000e0>

    @pytest.mark.error
    def test_unknown_associative_no_suggestion(self, cli):
        """Unknown ``--zzzzz`` with no close match → no suggestion.
    
        Spec: "unknown --<key> parameter" under Parameter errors header.
        """
        result = cli(["site", "create", "example.test", "--zzzzz=abc"])
        assert_exit_code(result, 1)
>       assert "unknown --zzzzz parameter" in result.stderr
E       AssertionError: assert 'unknown --zzzzz parameter' in 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E        +  where 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test', '--zzzzz=abc'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').stderr

.evaluation_tests/test_checkpoint_1.py:193: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestErrors::test_multiple_parameter_errors_collected  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestErrors object at 0x725329a619a0>
cli = <function cli.<locals>._run at 0x725328a00cc0>

    @pytest.mark.error
    def test_multiple_parameter_errors_collected(self, cli):
        """Two unknown associative args reported under single header.
    
        Spec: "they are collected and reported together under a
        ``Parameter errors:`` header."
        """
        result = cli(
            [
                "site",
                "create",
                "example.test",
                "--aaaa=x",
                "--bbbb=y",
            ]
        )
        assert_exit_code(result, 1)
>       assert "Parameter errors" in result.stderr
E       AssertionError: assert 'Parameter errors' in 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E        +  where 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test', '--aaaa=x', '--bbbb=y'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').stderr

.evaluation_tests/test_checkpoint_1.py:213: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_parent_command_no_handler_shows_subcommands  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestFunctionality object at 0x7253298fd730>
cli = <function cli.<locals>._run at 0x725328a01440>

    @pytest.mark.functionality
    def test_parent_command_no_handler_shows_subcommands(self, cli):
        """``appctl site`` (no direct handler) lists subcommands.
    
        Spec: "A command that has subcommands but no direct handler prints
        its usage."
        """
        result = cli(["site"])
        out = strip_ansi(result.stdout + result.stderr)
        # Should list available subcommands (create, delete, list, etc.)
>       assert "create" in out.lower() or "subcommand" in out.lower()
E       AssertionError: assert ('create' in 'error: container runtime is not installed or not running. please install and start the container runtime to run appctl.\n' or 'subcommand' in 'error: container runtime is not installed or not running. please install and start the container runtime to run appctl.\n')
E        +  where 'error: container runtime is not installed or not running. please install and start the container runtime to run appctl.\n' = <built-in method lower of str object at 0x725328b333c0>()
E        +    where <built-in method lower of str object at 0x725328b333c0> = 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'.lower
E        +  and   'error: container runtime is not installed or not running. please install and start the container runtime to run appctl.\n' = <built-in method lower of str object at 0x725328b333c0>()
E        +    where <built-in method lower of str object at 0x725328b333c0> = 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'.lower

.evaluation_tests/test_checkpoint_1.py:281: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_missing_error  [still failing since ck1]

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_empty_value_is_rejected  [still failing since ck1]

## .evaluation_tests/test_checkpoint_2.py::TestCore::test_config_runtime_overrides_project  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_project_config_local_yml_priority_overrides_project_disabled_command  [FIRST, REGRESSION]
```
ect at 0x7253299030e0>
cli = <function cli.<locals>._run at 0x725328a02a20>
write_config = <function write_config.<locals>._write at 0x725328a02ac0>
appctl_root = PosixPath('/tmp/pytest-of-agent/pytest-0/test_project_config_local_yml_1/appctl_root')

    @pytest.mark.functionality
    def test_project_config_local_yml_priority_overrides_project_disabled_command(
        self, cli, write_config, appctl_root
    ):
        """``appctl.local.yml`` wins over ``appctl.yml`` in one directory.
    
        Spec: "In a given directory, ``appctl.local.yml`` takes priority
        over ``appctl.yml``."
        """
        project_dir = appctl_root / "project"
        write_config(
            {"disabled_commands": ["site list"]},
            kind="project",
            project_dir=project_dir,
        )
        write_config(
            {"disabled_commands": []},
            kind="local",
            project_dir=project_dir,
        )
        result = cli(["site", "list"], cwd=project_dir)
    
>       assert_success(result)

.evaluation_tests/test_checkpoint_2.py:295: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', s...r: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n')
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
E         stderr: 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_project_config_search_stops_at_first_matching_directory  [FIRST, REGRESSION]
```
checkpoint_2.TestFunctionality object at 0x7253299031d0>
cli = <function cli.<locals>._run at 0x725328a02660>
appctl_root = PosixPath('/tmp/pytest-of-agent/pytest-0/test_project_config_search_sto0/appctl_root')

    @pytest.mark.functionality
    def test_project_config_search_stops_at_first_matching_directory(
        self, cli, appctl_root
    ):
        """Search stops at the nearest directory containing either config file.
    
        Spec: "The search stops at the first directory containing either
        file."
        """
        parent_dir = appctl_root / "project"
        child_dir = parent_dir / "child"
        nested_dir = child_dir / "nested"
        nested_dir.mkdir(parents=True)
    
        write_yaml(
            parent_dir / "appctl.local.yml",
            {"disabled_commands": ["site list"]},
        )
        write_yaml(
            child_dir / "appctl.yml",
            {"disabled_commands": []},
        )
    
        result = cli(["site", "list"], cwd=nested_dir)
>       assert_success(result)

.evaluation_tests/test_checkpoint_2.py:336: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', s...r: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n')
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
E         stderr: 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_strict_args_mode  [still failing since ck3, REGRESSION]

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::TestCore::test_table_format_default  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestCore object at 0x7253299033e0>
cli = <function cli.<locals>._run at 0x725328a03ce0>

    def test_table_format_default(self, cli):
        """Default output format is table with fixed-width columns.
    
        Spec: "The default output format is table."
        """
        result = cli(["site", "list", "--format=table"])
>       assert_success(result)

.evaluation_tests/test_checkpoint_3.py:37: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=table'], returnco...r: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n')
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
E         stderr: 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=table'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestCore::test_json_format_4_space_indent  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestCore object at 0x7253297bbf80>
cli = <function cli.<locals>._run at 0x725328a03e20>

    def test_json_format_4_space_indent(self, cli):
        """``--format=json`` produces pretty-printed JSON with 4-space indent.
    
        Spec: "Pretty-printed with 4-space indentation."
        """
        result = cli(["site", "list", "--format=json"])
>       assert_success(result)

.evaluation_tests/test_checkpoint_3.py:50: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=json'], returncod...r: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n')
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
E         stderr: 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=json'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestCore::test_field_single_value_raw_output  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestCore object at 0x7253297bbe30>
cli = <function cli.<locals>._run at 0x725328a709a0>

    def test_field_single_value_raw_output(self, cli):
        """``--field=<name>`` prints raw value, no table formatting.
    
        Spec: "--field=<name>: Outputs just that field's value directly
        to STDOUT without table formatting."
        """
        result = cli(["site", "list", "--field=status"])
>       assert_success(result)

.evaluation_tests/test_checkpoint_3.py:65: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--field=status'], returnco...r: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n')
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
E         stderr: 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--field=status'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestErrors::test_invalid_field_name_error  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestErrors object at 0x725328f70170>
cli = <function cli.<locals>._run at 0x725328a70a40>

    @pytest.mark.error
    def test_invalid_field_name_error(self, cli):
        """``--field=nonexistent`` → error to STDERR, exit 1.
    
        Spec: "Error: Invalid field: nonexistent."
        """
        result = cli(["site", "list", "--field=nonexistent"])
        assert_exit_code(result, 1)
>       assert "Invalid field" in result.stderr
E       AssertionError: assert 'Invalid field' in 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E        +  where 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--field=nonexistent'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').stderr

.evaluation_tests/test_checkpoint_3.py:122: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestErrors::test_invalid_json_stdin_error  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestErrors::test_confirmation_prompt_non_y_aborts  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestErrors object at 0x725328f72360>
cli = <function cli.<locals>._run at 0x725328a70180>

    @pytest.mark.error
    def test_confirmation_prompt_non_y_aborts(self, cli):
        """Confirmation prompt with response "n" aborts operation.
    
        Spec: "Any response other than y ... prints
        Warning: Operation cancelled."
        """
        cli(["site", "create", "example.test", "--type=html", "--yes"])
        result = cli(["site", "delete", "example.test"], input_text="n\n")
>       assert "Warning: Operation cancelled." in result.stderr
E       AssertionError: assert 'Warning: Operation cancelled.' in 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E        +  where 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').stderr

.evaluation_tests/test_checkpoint_3.py:146: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestErrors::test_invalid_fields_plural_error  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestErrors object at 0x725328f70800>
cli = <function cli.<locals>._run at 0x725328a03ce0>

    @pytest.mark.error
    def test_invalid_fields_plural_error(self, cli):
        """``--fields=name,nonexistent`` errors for invalid field.
    
        Spec: "Invalid field names produce: Error: Invalid field: <name>."
        """
        result = cli(["site", "list", "--fields=name,nonexistent"])
        assert_exit_code(result, 1)
>       assert "Invalid field" in result.stderr
E       AssertionError: assert 'Invalid field' in 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E        +  where 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--fields=name,nonexistent'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').stderr

.evaluation_tests/test_checkpoint_3.py:156: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_formats_preserve_same_underlying_values  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x725328f730b0>
cli = <function cli.<locals>._run at 0x725328a032e0>

    @pytest.mark.functionality
    def test_formats_preserve_same_underlying_values(self, cli):
        """`count` format item count matches `json` list length."""
        json_result = cli(["site", "list", "--format=json"])
        count_result = cli(["site", "list", "--format=count"])
>       assert_success(json_result)

.evaluation_tests/test_checkpoint_3.py:170: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=json'], returncod...r: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n')
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
E         stderr: 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=json'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_csv_format_quoting  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x725328f70380>
cli = <function cli.<locals>._run at 0x725328a70360>

    @pytest.mark.functionality
    def test_csv_format_quoting(self, cli):
        """CSV values with commas/quotes properly enclosed and escaped.
    
        Spec: "enclosed in double quotes. Embedded double quotes are escaped
        by doubling."
        """
        result = cli(["site", "list", "--format=csv"])
>       assert_success(result)

.evaluation_tests/test_checkpoint_3.py:183: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=csv'], returncode...r: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n')
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
E         stderr: 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=csv'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_csv_serializes_complex_values_as_json_strings  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_yaml_format_output  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7253297bb980>
cli = <function cli.<locals>._run at 0x725328a707c0>

    @pytest.mark.functionality
    def test_yaml_format_output(self, cli):
        """``--format=yaml`` produces standard YAML block style.
    
        Spec: Format table.
        """
        result = cli(["site", "list", "--format=yaml"])
>       assert_success(result)

.evaluation_tests/test_checkpoint_3.py:217: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=yaml'], returncod...r: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n')
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
E         stderr: 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=yaml'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_count_format_integer  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x725329902810>
cli = <function cli.<locals>._run at 0x725328a71300>

    @pytest.mark.functionality
    def test_count_format_integer(self, cli):
        """``--format=count`` outputs single integer count.
    
        Spec: "Single integer (number of result items)."
        """
        result = cli(["site", "list", "--format=count"])
>       assert_success(result)

.evaluation_tests/test_checkpoint_3.py:230: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=count'], returnco...r: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n')
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
E         stderr: 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=count'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_ids_format_space_separated  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x725329902cc0>
cli = <function cli.<locals>._run at 0x725328a70e00>

    @pytest.mark.functionality
    def test_ids_format_space_separated(self, cli):
        """``--format=ids`` outputs IDs space-separated on one line.
    
        Spec: "ID values on single line, space-separated."
        """
        result = cli(["site", "list", "--format=ids"])
>       assert_success(result)

.evaluation_tests/test_checkpoint_3.py:241: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=ids'], returncode...r: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n')
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
E         stderr: 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=ids'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_fields_restricts_and_orders_columns  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x725328f739b0>
cli = <function cli.<locals>._run at 0x725328a70220>

    @pytest.mark.functionality
    def test_fields_restricts_and_orders_columns(self, cli):
        """``--fields=status,name`` shows only those columns in that order.
    
        Spec: "restricts output to the specified columns, in the order listed."
        """
        result = cli(["site", "list", "--fields=status,name", "--format=csv"])
>       assert_success(result)

.evaluation_tests/test_checkpoint_3.py:253: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--fields=status,name', '--...r: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n')
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
E         stderr: 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--fields=status,name', '--format=csv'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_fields_case_insensitive  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x725328f71430>
cli = <function cli.<locals>._run at 0x725328a70040>

    @pytest.mark.functionality
    def test_fields_case_insensitive(self, cli):
        """``--fields=Status,NAME`` matches case-insensitively.
    
        Spec: "matched case-insensitively."
        """
        lower = cli(["site", "list", "--fields=status,name", "--format=csv"])
        mixed = cli(["site", "list", "--fields=Status,NAME", "--format=csv"])
>       assert_success(lower)

.evaluation_tests/test_checkpoint_3.py:265: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--fields=status,name', '--...r: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n')
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
E         stderr: 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--fields=status,name', '--format=csv'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_file_logging_separator_per_invocation  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_json_stdin_supplies_missing_positional_argument  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_confirmation_accepts_trimmed_uppercase_y  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7253297bb1d0>
cli = <function cli.<locals>._run at 0x725328a70540>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returnco...r: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n')
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
E         stderr: 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_confirmation_blank_response_cancels  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_quiet_does_not_suppress_debug_output  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_complex_values_json_serialized_in_table  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x725328f71940>
cli = <function cli.<locals>._run at 0x725328a713a0>

    @pytest.mark.functionality
    def test_complex_values_json_serialized_in_table(self, cli):
        """Array/object in table cell rendered as JSON string.
    
        Spec: "auto-serialized to their JSON string representation."
        """
        result = cli(["site", "list", "--format=table"])
>       assert_success(result)

.evaluation_tests/test_checkpoint_3.py:488: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=table'], returnco...r: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n')
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
E         stderr: 'Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=table'], returncode=1, stdout='', stderr='Error: Container runtime is not installed or not running. Please install and start the container runtime to run AppCtl.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_4.py::TestCore::test_detailed_execution_captures_all_fields  [still failing since ck4]

## .evaluation_tests/test_checkpoint_4.py::TestErrors::test_exit_code_negative_1_warning  [still failing since ck4]

## .evaluation_tests/test_checkpoint_5.py::TestCore::test_option_write_insert_then_read  [still failing since ck5]

## .evaluation_tests/test_checkpoint_5.py::TestCore::test_option_upsert_overwrites  [still failing since ck5]

## .evaluation_tests/test_checkpoint_5.py::TestFunctionality::test_all_values_stored_as_strings  [still failing since ck5]

## .evaluation_tests/test_checkpoint_5.py::TestFunctionality::test_empty_string_value_is_not_treated_as_missing  [still failing since ck5]

## .evaluation_tests/test_checkpoint_5.py::TestFunctionality::test_parameterized_queries  [still failing since ck5]

## .evaluation_tests/test_checkpoint_5.py::TestFunctionality::test_existing_db_opens_without_recreating  [still failing since ck5]

## .evaluation_tests/test_checkpoint_6.py::TestCore::test_compose_merge_base_always_first  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestCore::test_project_naming_prefix  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestCore::test_volume_creation_with_labels  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestErrors::test_container_runtime_not_installed_error  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_boot_container_exited_starts  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_boot_container_not_exists_creates  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_configured_custom_compose_applies_after_base  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_compose_directory_ignores_non_compose_files_in_call_order  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_compose_legacy_custom_appended_last  [FIRST, REGRESSION]
```
self = <test_checkpoint_6.TestFunctionality object at 0x725328dff3e0>
cli = <function cli.<locals>._run at 0x7253287a7060>
fake_docker_env = ({'PATH': '/tmp/pytest-of-agent/pytest-0/test_compose_legacy_custom_app0/fake_docker_bin:/tmp/uv-cache/archive-v0/VHgC.../local/games:/usr/games'}, PosixPath('/tmp/pytest-of-agent/pytest-0/test_compose_legacy_custom_app0/docker_calls.log'))
appctl_root = PosixPath('/tmp/pytest-of-agent/pytest-0/test_compose_legacy_custom_app0/appctl_root')

    @pytest.mark.functionality
    def test_compose_legacy_custom_appended_last(
        self, cli, fake_docker_env, appctl_root
    ):
        """Legacy custom compose files do not prevent compose execution.
    
        Spec: optional overrides may be discovered from runtime layout.
        """
        docker_env, _ = fake_docker_env
        services_dir = appctl_root / "services"
        services_dir.mkdir(exist_ok=True)
        write_yaml(services_dir / "docker-compose.yml", {"version": "3"})
        write_yaml(services_dir / "docker-compose-custom.yml", {"version": "3"})
        result = cli(["site", "list"], env=docker_env)
>       assert_success(result)

.evaluation_tests/test_checkpoint_6.py:470: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', stderr='Error: AppCtl requires compose tool version 2.0.0 or newer.\n')
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
E         stderr: 'Error: AppCtl requires compose tool version 2.0.0 or newer.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', stderr='Error: AppCtl requires compose tool version 2.0.0 or newer.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_missing_custom_compose_warns_and_falls_back_to_base  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_skip_tty_string_truthy_disables_tty  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_service_inspection_lists_names  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_volume_existing_is_silently_skipped  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_network_create_with_label  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_network_disconnect_failure_warning  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_site_delete_tears_down_containers_networks_and_volumes  [still failing since ck6]

## .evaluation_tests/test_checkpoint_7.py::TestCore::test_migration_discovery_and_ascending_sort  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestCore::test_migration_execution_creates_record  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestCore::test_migration_failure_triggers_batch_rollback  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestCore::test_disk_space_check_blocks_upgrade  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestErrors::test_migration_rollback_deletes_records  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestErrors::test_image_pull_failure_error  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_disk_space_exact_threshold_allows_upgrade  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_disk_space_failure_blocks_upgrade_mutations  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_runtime_disk_space_failure_blocks_upgrade_mutations  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_rollback_strict_reverse_order  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_rollback_undo_failure_logged_continues  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_rollback_no_undo_skipped  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_no_pending_migrations_do_not_duplicate_history  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_container_migrations_after_db_migrations  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_image_pulls_sequential  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_container_migration_failure_blocks_image_pulls  [still failing since ck7]

## .evaluation_tests/test_checkpoint_8.py::TestCore::test_sysreq_exponential_backoff_retries  [FIRST]
```
ecks retry with bounded increasing backoff.
    
            Spec: retry behavior is bounded and increasing.
            """
            # Create a docker that fails first 3 times then succeeds
            bin_dir = tmp_path / "backoff_bin"
            bin_dir.mkdir()
            counter_file = tmp_path / "attempt_count"
            counter_file.write_text("0")
    
            script = bin_dir / "docker"
            script.write_text(f"""#!/usr/bin/env python3
    import sys
    from pathlib import Path
    counter = Path("{counter_file}")
    count = int(counter.read_text()) + 1
    counter.write_text(str(count))
    if count < 3:
        sys.exit(1)
    else:
        sys.exit(0)
    """)
            script.chmod(0o755)
    
            # Also need docker-compose
            dc = bin_dir / "docker-compose"
            dc.write_text("#!/usr/bin/env sh\nexit 0\n")
            dc.chmod(0o755)
    
            env = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
            start = time.monotonic()
            result = cli(["site", "list"], env=env)
            elapsed = time.monotonic() - start
            attempts = int(counter_file.read_text())
>           assert_success(result)

.evaluation_tests/test_checkpoint_8.py:71: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', stderr='Error: AppCtl requires compose tool version 2.0.0 or newer.\n')
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
E         stderr: 'Error: AppCtl requires compose tool version 2.0.0 or newer.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', stderr='Error: AppCtl requires compose tool version 2.0.0 or newer.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestCore::test_version_newer_binary_triggers_migration  [FIRST]
```
self = <test_checkpoint_8.TestCore object at 0x725328e8f4d0>
cli = <function cli.<locals>._run at 0x725328689d00>
appctl_root = PosixPath('/tmp/pytest-of-agent/pytest-0/test_version_newer_binary_trig0/appctl_root')
db_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_version_newer_binary_trig0/appctl_root/db/appctl.sqlite')

    def test_version_newer_binary_triggers_migration(
        self, cli, appctl_root, db_path
    ):
        """Binary newer than DB version triggers migration.
    
        Spec: "Newer binary than database version: Triggers migration."
        """
        # Set a low version in the DB
        import sqlite3
    
        cli(["help"])  # Initialize
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
>           conn.execute(
                "INSERT OR REPLACE INTO options (key, value) VALUES (?, ?)",
                ("version", "0.0.1"),
            )
E           sqlite3.IntegrityError: NOT NULL constraint failed: options.modified_on

.evaluation_tests/test_checkpoint_8.py:119: IntegrityError
```

## .evaluation_tests/test_checkpoint_8.py::TestErrors::test_older_binary_non_cli_error  [FIRST]
```
self = <test_checkpoint_8.TestErrors object at 0x725328e8e240>
cli = <function cli.<locals>._run at 0x72532868ab60>
appctl_root = PosixPath('/tmp/pytest-of-agent/pytest-0/test_older_binary_non_cli_erro0/appctl_root')
db_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_older_binary_non_cli_erro0/appctl_root/db/appctl.sqlite')

    @pytest.mark.error
    def test_older_binary_non_cli_error(self, cli, appctl_root, db_path):
        """Older binary for non-cli command → error, exit 1.
    
        Spec: "Error directing to update."
        """
        import sqlite3
    
        cli(["help"])  # Initialize
        if not db_path.exists():
            return
    
        # Set a very high version in DB to simulate older binary
        conn = sqlite3.connect(str(db_path))
>       conn.execute(
            "INSERT OR REPLACE INTO options (key, value) VALUES (?, ?)",
            ("version", "99.99.99"),
        )
E       sqlite3.IntegrityError: NOT NULL constraint failed: options.modified_on

.evaluation_tests/test_checkpoint_8.py:202: IntegrityError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_older_binary_cli_warning  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x725328e8e8d0>
cli = <function cli.<locals>._run at 0x72532868ad40>
appctl_root = PosixPath('/tmp/pytest-of-agent/pytest-0/test_older_binary_cli_warning0/appctl_root')
db_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_older_binary_cli_warning0/appctl_root/db/appctl.sqlite')

    @pytest.mark.functionality
    def test_older_binary_cli_warning(self, cli, appctl_root, db_path):
        """Older binary for cli command → warning, proceeds.
    
        Spec: "Warning to STDERR."
        """
        import sqlite3
    
        cli(["help"])  # Initialize
        if not db_path.exists():
            return
    
        conn = sqlite3.connect(str(db_path))
>       conn.execute(
            "INSERT OR REPLACE INTO options (key, value) VALUES (?, ?)",
            ("version", "99.99.99"),
        )
E       sqlite3.IntegrityError: NOT NULL constraint failed: options.modified_on

.evaluation_tests/test_checkpoint_8.py:302: IntegrityError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_runtime_binary_resolution_precedence  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x725328e8f590>
cli = <function cli.<locals>._run at 0x72532868b880>
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_runtime_binary_resolution0')

    @pytest.mark.functionality
    def test_runtime_binary_resolution_precedence(self, cli, tmp_path):
        """``APPCTL_RUNTIME_BIN`` > ``APPCTL_RUNTIME_BIN_USED`` > default.
    
        Spec: Precedence list.
        """
        fake_bin = tmp_path / "fake_runtime"
        fake_bin.write_text("#!/usr/bin/env sh\nexit 0\n")
        fake_bin.chmod(0o755)
    
        result = cli(
            ["cli", "info", "--format=json"],
            env={"APPCTL_RUNTIME_BIN": str(fake_bin)},
        )
        assert_success(result)
        data = json.loads(result.stdout)
        runtime_path_values = [
            value
            for key, value in data.items()
            if "runtime" in key.casefold() and "path" in key.casefold()
        ]
>       assert runtime_path_values, "Expected runtime path diagnostics."
E       AssertionError: Expected runtime path diagnostics.
E       assert []

.evaluation_tests/test_checkpoint_8.py:367: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_info_list_format_field_order  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x725328e8dbb0>
cli = <function cli.<locals>._run at 0x72532868bce0>

    @pytest.mark.functionality
    def test_cli_info_list_format_field_order(self, cli):
        """List format includes core diagnostic fields.
    
        Spec: stable diagnostic semantics in list format.
        """
        result = cli(["cli", "info"])
        assert_success(result)
        out = strip_ansi(result.stdout)
        keys = [
            line.split(":", 1)[0].strip()
            for line in out.splitlines()
            if ":" in line
        ]
        keyset = {k.casefold() for k in keys}
        assert "os" in keyset
        assert "shell" in keyset
>       assert "version" in keyset
E       AssertionError: assert 'version' in {'appctl binary path', 'path', 'debug', 'os', 'success', 'appctl version', 'appctl cache dir', 'user', 'appctl packages dir', 'python binary', 'strict arguments mode', 'color', 'appctl global config', 'shell', 'python version', 'quiet', 'appctl archive path', 'appctl root dir', 'appctl dir path', 'appctl project config', 'appctl release channel', 'python prefix', 'url', 'appctl stored version'}

.evaluation_tests/test_checkpoint_8.py:401: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_check_update_last_filter_wins  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x725328e8ce60>
cli = <function cli.<locals>._run at 0x72532868b4c0>

    @pytest.mark.functionality
    def test_cli_check_update_last_filter_wins(self, cli):
        """``--patch --minor`` → minor wins.
    
        Spec: "the last one wins."
        """
        result = cli(["cli", "check-update", "--patch", "--minor"])
>       assert "minor" in (result.stdout + result.stderr).lower()
E       AssertionError: assert 'minor' in 'success: appctl has been set up successfully.\nerror: failed to get the latest version from https://api.github.com/repos/appctl/appctl/releases?per_page=100: tunnel connection failed: 403 filtered\n'
E        +  where 'success: appctl has been set up successfully.\nerror: failed to get the latest version from https://api.github.com/repos/appctl/appctl/releases?per_page=100: tunnel connection failed: 403 filtered\n' = <built-in method lower of str object at 0x725328652f10>()
E        +    where <built-in method lower of str object at 0x725328652f10> = ('Success: AppCtl has been set up successfully.\n' + 'Error: Failed to get the latest version from https://api.github.com/repos/appctl/appctl/releases?per_page=100: Tunnel connection failed: 403 Filtered\n').lower
E        +      where 'Success: AppCtl has been set up successfully.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update', '--patch', '--minor'], returncode=1, stdout='Success: AppCtl has been set up successfully.\n', stderr='Error: Failed to get the latest version from https://api.github.com/repos/appctl/appctl/releases?per_page=100: Tunnel connection failed: 403 Filtered\n').stdout
E        +      and   'Error: Failed to get the latest version from https://api.github.com/repos/appctl/appctl/releases?per_page=100: Tunnel connection failed: 403 Filtered\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update', '--patch', '--minor'], returncode=1, stdout='Success: AppCtl has been set up successfully.\n', stderr='Error: Failed to get the latest version from https://api.github.com/repos/appctl/appctl/releases?per_page=100: Tunnel connection failed: 403 Filtered\n').stderr

.evaluation_tests/test_checkpoint_8.py:442: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_check_update_no_updates_success  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x725328e8da30>
cli = <function cli.<locals>._run at 0x72532868ad40>

    @pytest.mark.functionality
    def test_cli_check_update_no_updates_success(self, cli):
        """No updates available prints success message.
    
        Spec: emits a success message indicating the tool is up to date.
        """
        result = cli(["cli", "check-update"])
>       assert_success(result)

.evaluation_tests/test_checkpoint_8.py:451: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update'], returncode=1, stdou...rsion from https://api.github.com/repos/appctl/appctl/releases?per_page=100: Tunnel connection failed: 403 Filtered\n')
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
E         stdout: 'Success: AppCtl has been set up successfully.\n'
E         stderr: 'Error: Failed to get the latest version from https://api.github.com/repos/appctl/appctl/releases?per_page=100: Tunnel connection failed: 403 Filtered\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update'], returncode=1, stdout='Success: AppCtl has been set up successfully.\n', stderr='Error: Failed to get the latest version from https://api.github.com/repos/appctl/appctl/releases?per_page=100: Tunnel connection failed: 403 Filtered\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_check_update_table_format_no_updates_success  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x725328e8c2f0>
cli = <function cli.<locals>._run at 0x725328688040>

    @pytest.mark.functionality
    def test_cli_check_update_table_format_no_updates_success(self, cli):
        """Explicit table format still emits the no-update success message.
    
        Spec: "If no updates are available and the format is `table` or
        omitted, the tool must print a success message indicating the tool is
        up to date."
        """
        result = cli(["cli", "check-update", "--format=table"])
>       assert_success(result)

.evaluation_tests/test_checkpoint_8.py:465: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update', '--format=table'], r...rsion from https://api.github.com/repos/appctl/appctl/releases?per_page=100: Tunnel connection failed: 403 Filtered\n')
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
E         stdout: 'Success: AppCtl has been set up successfully.\n'
E         stderr: 'Error: Failed to get the latest version from https://api.github.com/repos/appctl/appctl/releases?per_page=100: Tunnel connection failed: 403 Filtered\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update', '--format=table'], returncode=1, stdout='Success: AppCtl has been set up successfully.\n', stderr='Error: Failed to get the latest version from https://api.github.com/repos/appctl/appctl/releases?per_page=100: Tunnel connection failed: 403 Filtered\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_check_update_filtered_no_updates_mentions_filter  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x725328e8d610>
cli = <function cli.<locals>._run at 0x72532868ab60>

    @pytest.mark.functionality
    def test_cli_check_update_filtered_no_updates_mentions_filter(
        self,
        cli,
    ):
        """Filtered no-update success includes the active filter type.
    
        Spec: "If a filter is active and no updates are available, the success
        message must include the filter type."
        """
        result = cli(["cli", "check-update", "--patch"])
>       assert_success(result)

.evaluation_tests/test_checkpoint_8.py:479: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
.evaluation_tests/conftest.py:322: in assert_success
    assert_exit_code(result, 0)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update', '--patch'], returnco...rsion from https://api.github.com/repos/appctl/appctl/releases?per_page=100: Tunnel connection failed: 403 Filtered\n')
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
E         stdout: 'Success: AppCtl has been set up successfully.\n'
E         stderr: 'Error: Failed to get the latest version from https://api.github.com/repos/appctl/appctl/releases?per_page=100: Tunnel connection failed: 403 Filtered\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update', '--patch'], returncode=1, stdout='Success: AppCtl has been set up successfully.\n', stderr='Error: Failed to get the latest version from https://api.github.com/repos/appctl/appctl/releases?per_page=100: Tunnel connection failed: 403 Filtered\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_update_requires_confirmation  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x725328e8c470>
cli = <function cli.<locals>._run at 0x72532868a7a0>

    @pytest.mark.functionality
    def test_cli_update_requires_confirmation(self, cli):
        """Update without ``--yes`` prompts user.
    
        Spec: "Requires confirmation before proceeding."
        """
        result = cli(["cli", "update"], input_text="n\n")
        combined = result.stdout + result.stderr
        if sys.platform == "darwin":
            assert "Self-update is not available" in result.stderr
        else:
>           assert "[y/n]" in combined
E           AssertionError: assert '[y/n]' in 'Success: AppCtl has been set up successfully.\nError: Failed to get the latest version from https://api.github.com/repos/appctl/appctl/releases?per_page=100: Tunnel connection failed: 403 Filtered\n'

.evaluation_tests/test_checkpoint_8.py:495: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_param_dump_with_values_reflects_runtime_config  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x725328e8d040>
cli = <function cli.<locals>._run at 0x72532868afc0>
write_config = <function write_config.<locals>._write at 0x72532868bc40>

    @pytest.mark.functionality
    def test_cli_param_dump_with_values_reflects_runtime_config(
        self,
        cli,
        write_config,
    ):
        """``--with-values`` includes each parameter's current runtime value.
    
        Spec: "`--with-values` includes the current runtime value for each
        parameter."
        """
        write_config({"color": False}, kind="global")
    
        result = cli(["cli", "param-dump", "--with-values"])
        assert_success(result)
    
        data = json.loads(result.stdout)
        assert "color" in data
        assert isinstance(data["color"], dict)
>       assert data["color"].get("value") is False
E       AssertionError: assert None is False
E        +  where None = <built-in method get of dict object at 0x725328c42480>('value')
E        +    where <built-in method get of dict object at 0x725328c42480> = {'runtime': '[--[no-]color]', 'file': True, 'default': 'auto', 'desc': 'Whether to colorize the output.', 'current': False}.get

.evaluation_tests/test_checkpoint_8.py:551: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_cmd_dump_alphabetical  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x725328e8f5f0>
cli = <function cli.<locals>._run at 0x725328688c20>

    @pytest.mark.functionality
    def test_cli_cmd_dump_alphabetical(self, cli):
        """Commands sorted alphabetically by full path.
    
        Spec: "sorted alphabetically by full command path."
        """
        result = cli(["cli", "cmd-dump"])
        assert_success(result)
        data = json.loads(result.stdout)
        if isinstance(data, dict):
            keys = list(data.keys())
>           assert keys == sorted(keys)
E           AssertionError: assert ['name', 'description', 'longdesc', 'subcommands'] == ['description', 'longdesc', 'name', 'subcommands']
E             
E             At index 0 diff: 'name' != 'description'
E             
E             Full diff: (-: missing in left side, +: extra in left side)
E               [
E             +     'name',
E                   'description',
E                   'longdesc',
E             -     'name',
E                   'subcommands',
E               ]

.evaluation_tests/test_checkpoint_8.py:585: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_param_dump_var_export_output  [FIRST]
```
default\' => NULL,\n    \'desc\' => \'Custom compose file.\',\n  ),\n  \'debug\' => \n  array (\n    \'runtime\' => \'[--debug[=<group>]]\',\n    \'file\' => false,\n    \'default\' => false,\n    \'desc\' => \'Show all errors and add verbosity to bootstrap.\',\n  ),\n  \'disabled_commands\' => \n  array (\n    \'runtime\' => false,\n    \'file\' => true,\n    \'default\' => \n    array (\n    ),\n    \'desc\' => \'(Sub)commands to disable.\',\n  ),\n  \'env\' => \n  array (\n    \'runtime\' => false,\n    \'file\' => true,\n    \'default\' => NULL,\n    \'desc\' => \'Environment name.\',\n  ),\n  \'installer_version\' => \n  array (\n    \'runtime\' => false,\n    \'file\' => true,\n    \'default\' => \'stable\',\n    \'desc\' => \'Installer release channel.\',\n  ),\n  \'locale\' => \n  array (\n    \'runtime\' => false,\n    \'file\' => true,\n    \'default\' => \'en_US\',\n    \'desc\' => \'Locale to use.\',\n  ),\n  \'path\' => \n  array (\n    \'runtime\' => \'[--path=<path>]\',\n    \'file\' => true,\n    \'default\' => NULL,\n    \'desc\' => \'Path to the application files.\',\n  ),\n  \'projects_path\' => \n  array (\n    \'runtime\' => false,\n    \'file\' => true,\n    \'default\' => NULL,\n    \'desc\' => \'Directory in which projects are stored.\',\n  ),\n  \'quiet\' => \n  array (\n    \'runtime\' => \'[--quiet]\',\n    \'file\' => false,\n    \'default\' => false,\n    \'desc\' => \'Suppress informational messages.\',\n  ),\n  \'skip-tty\' => \n  array (\n    \'runtime\' => false,\n    \'file\' => true,\n    \'default\' => false,\n    \'desc\' => \'Do not allocate a TTY for remote commands.\',\n  ),\n  \'ssh\' => \n  array (\n    \'runtime\' => \'[--ssh=<ssh>]\',\n    \'file\' => true,\n    \'default\' => NULL,\n    \'desc\' => \'Perform operation against a remote server over SSH (or a container using scheme of "docker", "docker-compose", "docker-compose-run", "vagrant").\',\n  ),\n  \'sysctl\' => \n  array (\n    \'runtime\' => false,\n    \'file\' => true,\n    \'default\' => NULL,\n    \'desc\' => \'Kernel parameters to apply.\',\n  ),\n  \'url\' => \n  array (\n    \'runtime\' => \'[--url=<url>]\',\n    \'file\' => true,\n    \'default\' => NULL,\n    \'desc\' => \'Pretend request came from given URL.\',\n  ),\n  \'user\' => \n  array (\n    \'runtime\' => \'[--user=<id>]\',\n    \'file\' => true,\n    \'default\' => NULL,\n    \'desc\' => \'Set the user.\',\n  ),\n)'.startswith

.evaluation_tests/test_checkpoint_8.py:674: AssertionError
```
