# Checkpoint 8 hidden-test results

Outcomes: {'passed': 164, 'failed': 90, 'skipped': 1}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_1.py::TestCore::test_help_rewrite  [FIRST, REGRESSION]
```
ess(rewritten)
        assert_success(direct)
>       assert (
            strip_ansi(rewritten.stdout).strip()
            == strip_ansi(direct.stdout).strip()
        )
E       assert "Success: appctl has been set up successfully.\nNAME\n\n  appctl site\n\nDESCRIPTION\n\n  Create, delete, list, and update sites.\n\nSYNOPSIS\n\n  appctl site <command>\n\nSUBCOMMANDS\n\n  activate    Activate one or more sites.\n  config      Display the merged compose configuration of a site.\n  create      Create a site.\n  deactivate  Deactivate one or more sites.\n  delete      Delete a site.\n  empty       Empty a site of its content.\n  list        List all sites.\n  meta        Add, update, get, and delete site metadata.\n  update      Update one or more fields of a site.\n\nSee 'appctl help site <command>' for more information on a specific command." == "NAME\n\n  appctl site\n\nDESCRIPTION\n\n  Create, delete, list, and update sites.\n\nSYNOPSIS\n\n  appctl site <command>\n\nSUBCOMMANDS\n\n  activate    Activate one or more sites.\n  config      Display the merged compose configuration of a site.\n  create      Create a site.\n  deactivate  Deactivate one or more sites.\n  delete      Delete a site.\n  empty       Empty a site of its content.\n  list        List all sites.\n  meta        Add, update, get, and delete site metadata.\n  update      Update one or more fields of a site.\n\nSee 'appctl help site <command>' for more information on a specific command."
E         
E         + Success: appctl has been set up successfully.
E           NAME
E           
E             appctl site
E           
E           DESCRIPTION
E           
E             Create, delete, list, and update sites.
E           
E           SYNOPSIS
E           
E             appctl site <command>
E           
E           SUBCOMMANDS
E           
E             activate    Activate one or more sites.
E             config      Display the merged compose configuration of a site.
E             create      Create a site.
E             deactivate  Deactivate one or more sites.
E             delete      Delete a site.
E             empty       Empty a site of its content.
E             list        List all sites.
E             meta        Add, update, get, and delete site metadata.
E             update      Update one or more fields of a site.
E           
E           See 'appctl help site <command>' for more information on a specific command.

.evaluation_tests/test_checkpoint_1.py:89: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestCore::test_help_rewrite_for_multi_level_command  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestCore object at 0x7e71f18a5b80>
cli = <function cli.<locals>._run at 0x7e71f095ff60>

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
E       AssertionError: assert 'Success: appctl has been set up successfully.\nNAME\n\n  appctl site create\n\nDESCRIPTION\n\n  Create a site.\n\nSYNOPSIS\n\n  appctl site create <site-name> [--type=<type>] [--title=<title>] [--email=<email>] [--porcelain]\n\nOPTIONS\n\n  <site-name>\n  [--type=<type>]\n    default: standard\n  [--title=<title>]\n  [--email=<email>]\n  [--porcelain]' == 'NAME\n\n  appctl site create\n\nDESCRIPTION\n\n  Create a site.\n\nSYNOPSIS\n\n  appctl site create <site-name> [--type=<type>] [--title=<title>] [--email=<email>] [--porcelain]\n\nOPTIONS\n\n  <site-name>\n  [--type=<type>]\n    default: standard\n  [--title=<title>]\n  [--email=<email>]\n  [--porcelain]'
E         
E         + Success: appctl has been set up successfully.
E           NAME
E           
E             appctl site create
E           
E           DESCRIPTION
E           
E             Create a site.
E           
E           SYNOPSIS
E           
E             appctl site create <site-name> [--type=<type>] [--title=<title>] [--email=<email>] [--porcelain]
E           
E           OPTIONS
E           
E             <site-name>
E             [--type=<type>]
E               default: standard
E             [--title=<title>]
E             [--email=<email>]
E             [--porcelain]

.evaluation_tests/test_checkpoint_1.py:105: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestErrors::test_missing_required_positional_shows_usage  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestErrors object at 0x7e71f173d9d0>
cli = <function cli.<locals>._run at 0x7e71f0878680>

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
E       AssertionError: assert ('usage:' in '' or 'usage:' in 'error: container runtime (docker) is either not installed or not running.\n')
E        +  where '' = <built-in method lower of str object at 0x7e71f2f07290>()
E        +    where <built-in method lower of str object at 0x7e71f2f07290> = ''.lower
E        +      where '' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', '--type=html'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').stdout
E        +  and   'error: container runtime (docker) is either not installed or not running.\n' = <built-in method lower of str object at 0x7e71f0accf30>()
E        +    where <built-in method lower of str object at 0x7e71f0accf30> = 'Error: Container runtime (docker) is either not installed or not running.\n'.lower
E        +      where 'Error: Container runtime (docker) is either not installed or not running.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', '--type=html'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').stderr

.evaluation_tests/test_checkpoint_1.py:159: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestErrors::test_excess_positional_args_error  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestErrors object at 0x7e71f173cb90>
cli = <function cli.<locals>._run at 0x7e71f0878ae0>

    @pytest.mark.error
    def test_excess_positional_args_error(self, cli):
        """Extra positional args without repeating token → error.
    
        Spec: "Error: Too many positional arguments: extra-arg" Example 6.
        """
        result = cli(["site", "create", "example.test", "extra-arg"])
        assert_exit_code(result, 1)
>       assert "Too many positional arguments" in result.stderr
E       AssertionError: assert 'Too many positional arguments' in 'Error: Container runtime (docker) is either not installed or not running.\n'
E        +  where 'Error: Container runtime (docker) is either not installed or not running.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test', 'extra-arg'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').stderr

.evaluation_tests/test_checkpoint_1.py:172: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestErrors::test_unknown_associative_with_suggestion  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestErrors object at 0x7e71f18a53d0>
cli = <function cli.<locals>._run at 0x7e71f0878f40>

    @pytest.mark.error
    def test_unknown_associative_with_suggestion(self, cli):
        """Unknown ``--typo`` with registered ``--type`` (dist ≤ 2) → suggestion.
    
        Spec: Example 5.
        """
        result = cli(["site", "create", "example.test", "--typo=html"])
        assert_exit_code(result, 1)
>       assert "Parameter errors" in result.stderr
E       AssertionError: assert 'Parameter errors' in 'Error: Container runtime (docker) is either not installed or not running.\n'
E        +  where 'Error: Container runtime (docker) is either not installed or not running.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test', '--typo=html'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').stderr

.evaluation_tests/test_checkpoint_1.py:182: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestErrors::test_unknown_associative_no_suggestion  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestErrors object at 0x7e71f18a4ef0>
cli = <function cli.<locals>._run at 0x7e71f0878180>

    @pytest.mark.error
    def test_unknown_associative_no_suggestion(self, cli):
        """Unknown ``--zzzzz`` with no close match → no suggestion.
    
        Spec: "unknown --<key> parameter" under Parameter errors header.
        """
        result = cli(["site", "create", "example.test", "--zzzzz=abc"])
        assert_exit_code(result, 1)
>       assert "unknown --zzzzz parameter" in result.stderr
E       AssertionError: assert 'unknown --zzzzz parameter' in 'Error: Container runtime (docker) is either not installed or not running.\n'
E        +  where 'Error: Container runtime (docker) is either not installed or not running.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test', '--zzzzz=abc'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').stderr

.evaluation_tests/test_checkpoint_1.py:193: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestErrors::test_multiple_parameter_errors_collected  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestErrors object at 0x7e71f18a5a90>
cli = <function cli.<locals>._run at 0x7e71f0878d60>

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
E       AssertionError: assert 'Parameter errors' in 'Error: Container runtime (docker) is either not installed or not running.\n'
E        +  where 'Error: Container runtime (docker) is either not installed or not running.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'create', 'example.test', '--aaaa=x', '--bbbb=y'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').stderr

.evaluation_tests/test_checkpoint_1.py:213: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestErrors::test_unrecognized_subcommand_error  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestErrors object at 0x7e71f18a6120>
cli = <function cli.<locals>._run at 0x7e71f0879120>

    @pytest.mark.error
    def test_unrecognized_subcommand_error(self, cli):
        """``appctl site bogus`` → subcommand error, exit 1.
    
        Spec: "Error: '<subcommand>' is not a registered subcommand of
        '<parent>'."
        """
        result = cli(["site", "bogus"])
>       assert_error(result, "is not a registered subcommand of")

.evaluation_tests/test_checkpoint_1.py:225: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'bogus'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
message = 'is not a registered subcommand of'

    def assert_error(
        result: subprocess.CompletedProcess[str],
        message: str | None = None,
    ) -> None:
        """Assert the process failed; optionally check stderr contains *message*."""
        assert result.returncode != 0, (
            f"Expected non-zero exit, got 0.\nstdout: {result.stdout!r}"
        )
        if message is not None:
>           assert message in result.stderr, (
                f"Expected {message!r} in stderr.\nstderr: {result.stderr!r}"
            )
E           AssertionError: Expected 'is not a registered subcommand of' in stderr.
E             stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E           assert 'is not a registered subcommand of' in 'Error: Container runtime (docker) is either not installed or not running.\n'
E            +  where 'Error: Container runtime (docker) is either not installed or not running.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'bogus'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').stderr

.evaluation_tests/conftest.py:334: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_parent_command_no_handler_shows_subcommands  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestFunctionality object at 0x7e71f173d550>
cli = <function cli.<locals>._run at 0x7e71f0878cc0>

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
E       AssertionError: assert ('create' in 'error: container runtime (docker) is either not installed or not running.\n' or 'subcommand' in 'error: container runtime (docker) is either not installed or not running.\n')
E        +  where 'error: container runtime (docker) is either not installed or not running.\n' = <built-in method lower of str object at 0x7e71f07f1930>()
E        +    where <built-in method lower of str object at 0x7e71f07f1930> = 'Error: Container runtime (docker) is either not installed or not running.\n'.lower
E        +  and   'error: container runtime (docker) is either not installed or not running.\n' = <built-in method lower of str object at 0x7e71f07f1930>()
E        +    where <built-in method lower of str object at 0x7e71f07f1930> = 'Error: Container runtime (docker) is either not installed or not running.\n'.lower

.evaluation_tests/test_checkpoint_1.py:281: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_subcommand_synonym_example_allows_optional_delete_suggestion  [FIRST, REGRESSION]
```
self = <test_checkpoint_1.TestFunctionality object at 0x7e71f173c3e0>
cli = <function cli.<locals>._run at 0x7e71f0879080>

    @pytest.mark.functionality
    def test_subcommand_synonym_example_allows_optional_delete_suggestion(
        self, cli
    ):
        """Subcommand errors stay valid whether or not synonym hints are shown.
    
        Spec: curated synonym suggestions are optional.
        """
        result = cli(["site", "trash"])
        assert_exit_code(result, 1)
>       assert_stderr_contains(
            result,
            "Error: 'trash' is not a registered subcommand of 'site'.",
            "See 'appctl help site' for available subcommands.",
        )

.evaluation_tests/test_checkpoint_1.py:304: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'trash'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
fragments = ("Error: 'trash' is not a registered subcommand of 'site'.", "See 'appctl help site' for available subcommands.")

    def assert_stderr_contains(
        result: subprocess.CompletedProcess[str], *fragments: str
    ) -> None:
        """Assert all *fragments* appear in stderr."""
        for frag in fragments:
>           assert frag in result.stderr, (
                f"Missing {frag!r} in stderr.\nstderr: {result.stderr!r}"
            )
E           AssertionError: Missing "Error: 'trash' is not a registered subcommand of 'site'." in stderr.
E             stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E           assert "Error: 'trash' is not a registered subcommand of 'site'." in 'Error: Container runtime (docker) is either not installed or not running.\n'
E            +  where 'Error: Container runtime (docker) is either not installed or not running.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'trash'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').stderr

.evaluation_tests/conftest.py:344: AssertionError
```

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_missing_error  [still failing since ck1]

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_empty_value_is_rejected  [still failing since ck1]

## .evaluation_tests/test_checkpoint_2.py::TestCore::test_disabled_command_error  [FIRST, REGRESSION]
```
self = <test_checkpoint_2.TestCore object at 0x7e71f173dbe0>
cli = <function cli.<locals>._run at 0x7e71f087a160>
write_config = <function write_config.<locals>._write at 0x7e71f08798a0>

    def test_disabled_command_error(self, cli, write_config):
        """Disabled command → exact error message to STDERR, exit 1.
    
        Spec: "Error: The '<command>' command has been disabled."
        """
        write_config({"disabled_commands": ["site delete"]}, kind="global")
        result = cli(["site", "delete", "example.test"])
        assert_exit_code(result, 1)
>       assert "has been disabled" in result.stderr
E       AssertionError: assert 'has been disabled' in 'Error: Container runtime (docker) is either not installed or not running.\n'
E        +  where 'Error: Container runtime (docker) is either not installed or not running.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').stderr

.evaluation_tests/test_checkpoint_2.py:170: AssertionError
```

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_project_config_local_yml_priority_overrides_project_disabled_command  [FIRST, REGRESSION]
```
self = <test_checkpoint_2.TestFunctionality object at 0x7e71f173d130>
cli = <function cli.<locals>._run at 0x7e71f087b380>
write_config = <function write_config.<locals>._write at 0x7e71f087ac00>
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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
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
E         stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_project_config_search_stops_at_first_matching_directory  [FIRST, REGRESSION]
```
self = <test_checkpoint_2.TestFunctionality object at 0x7e71f17426c0>
cli = <function cli.<locals>._run at 0x7e71f087a980>
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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
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
E         stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_yaml_merge_arrays_appended  [FIRST, REGRESSION]
```
self = <test_checkpoint_2.TestFunctionality object at 0x7e71f1742de0>
cli = <function cli.<locals>._run at 0x7e71f087ade0>
appctl_root = PosixPath('/tmp/pytest-of-agent/pytest-0/test_yaml_merge_arrays_appende0/appctl_root')
write_config = <function write_config.<locals>._write at 0x7e71f087a480>

    @pytest.mark.functionality
    def test_yaml_merge_arrays_appended(self, cli, appctl_root, write_config):
        """``_: {merge: true}`` appends arrays instead of replacing.
    
        Spec: Example 5.
        """
        config_dir = appctl_root / "config"
        base_path = config_dir / "base.yml"
        write_yaml(base_path, {"disabled_commands": ["site delete"]})
        write_yaml(
            config_dir / "config.yml",
            {
                "_": {"inherit": str(base_path), "merge": True},
                "disabled_commands": ["cli update"],
            },
        )
        result = cli(["site", "delete", "example.test"])
        assert_exit_code(result, 1)
>       assert "has been disabled" in result.stderr
E       AssertionError: assert 'has been disabled' in 'Error: Container runtime (docker) is either not installed or not running.\n'
E        +  where 'Error: Container runtime (docker) is either not installed or not running.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').stderr

.evaluation_tests/test_checkpoint_2.py:373: AssertionError
```

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_yaml_merge_arrays_not_deduplicated  [FIRST, REGRESSION]
```
self = <test_checkpoint_2.TestFunctionality object at 0x7e71f1743e30>
cli = <function cli.<locals>._run at 0x7e71f0879da0>
appctl_root = PosixPath('/tmp/pytest-of-agent/pytest-0/test_yaml_merge_arrays_not_ded0/appctl_root')

    @pytest.mark.functionality
    def test_yaml_merge_arrays_not_deduplicated(self, cli, appctl_root):
        """Merged arrays are not deduplicated.
    
        Spec: "Arrays are not deduplicated."
        """
        config_dir = appctl_root / "config"
        base_path = config_dir / "base.yml"
        write_yaml(base_path, {"disabled_commands": ["site delete"]})
        write_yaml(
            config_dir / "config.yml",
            {
                "_": {"inherit": str(base_path), "merge": True},
                "disabled_commands": ["site delete"],
            },
        )
        # Both entries should exist (duplicated)
        result = cli(["site", "delete", "example.test"])
        assert_exit_code(result, 1)
>       assert "has been disabled" in result.stderr
E       AssertionError: assert 'has been disabled' in 'Error: Container runtime (docker) is either not installed or not running.\n'
E        +  where 'Error: Container runtime (docker) is either not installed or not running.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').stderr

.evaluation_tests/test_checkpoint_2.py:394: AssertionError
```

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::TestCore::test_table_format_default  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestCore object at 0x7e71f1743fe0>
cli = <function cli.<locals>._run at 0x7e71f08a0540>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=table'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
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
E         stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=table'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestCore::test_json_format_4_space_indent  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestCore object at 0x7e71f173c3b0>
cli = <function cli.<locals>._run at 0x7e71f08a0040>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=json'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
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
E         stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=json'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestCore::test_field_single_value_raw_output  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestCore object at 0x7e71f15fb140>
cli = <function cli.<locals>._run at 0x7e71f08a04a0>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--field=status'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
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
E         stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--field=status'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestErrors::test_invalid_field_name_error  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestErrors object at 0x7e71f0da8350>
cli = <function cli.<locals>._run at 0x7e71f0879da0>

    @pytest.mark.error
    def test_invalid_field_name_error(self, cli):
        """``--field=nonexistent`` → error to STDERR, exit 1.
    
        Spec: "Error: Invalid field: nonexistent."
        """
        result = cli(["site", "list", "--field=nonexistent"])
        assert_exit_code(result, 1)
>       assert "Invalid field" in result.stderr
E       AssertionError: assert 'Invalid field' in 'Error: Container runtime (docker) is either not installed or not running.\n'
E        +  where 'Error: Container runtime (docker) is either not installed or not running.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--field=nonexistent'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').stderr

.evaluation_tests/test_checkpoint_3.py:122: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestErrors::test_invalid_json_stdin_error  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestErrors::test_confirmation_prompt_non_y_aborts  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestErrors object at 0x7e71f0daa480>
cli = <function cli.<locals>._run at 0x7e71f08a11c0>

    @pytest.mark.error
    def test_confirmation_prompt_non_y_aborts(self, cli):
        """Confirmation prompt with response "n" aborts operation.
    
        Spec: "Any response other than y ... prints
        Warning: Operation cancelled."
        """
        cli(["site", "create", "example.test", "--type=html", "--yes"])
        result = cli(["site", "delete", "example.test"], input_text="n\n")
>       assert "Warning: Operation cancelled." in result.stderr
E       AssertionError: assert 'Warning: Operation cancelled.' in 'Error: Container runtime (docker) is either not installed or not running.\n'
E        +  where 'Error: Container runtime (docker) is either not installed or not running.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').stderr

.evaluation_tests/test_checkpoint_3.py:146: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestErrors::test_invalid_fields_plural_error  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestErrors object at 0x7e71f0da9cd0>
cli = <function cli.<locals>._run at 0x7e71f08a0c20>

    @pytest.mark.error
    def test_invalid_fields_plural_error(self, cli):
        """``--fields=name,nonexistent`` errors for invalid field.
    
        Spec: "Invalid field names produce: Error: Invalid field: <name>."
        """
        result = cli(["site", "list", "--fields=name,nonexistent"])
        assert_exit_code(result, 1)
>       assert "Invalid field" in result.stderr
E       AssertionError: assert 'Invalid field' in 'Error: Container runtime (docker) is either not installed or not running.\n'
E        +  where 'Error: Container runtime (docker) is either not installed or not running.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--fields=name,nonexistent'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').stderr

.evaluation_tests/test_checkpoint_3.py:156: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_formats_preserve_same_underlying_values  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e71f0da8890>
cli = <function cli.<locals>._run at 0x7e71f08a1440>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=json'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
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
E         stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=json'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_csv_format_quoting  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e71f0da8410>
cli = <function cli.<locals>._run at 0x7e71f08a0ea0>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=csv'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
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
E         stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=csv'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_csv_serializes_complex_values_as_json_strings  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_yaml_format_output  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e71f15fb9e0>
cli = <function cli.<locals>._run at 0x7e71f08a0b80>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=yaml'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
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
E         stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=yaml'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_count_format_integer  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e71f173cb30>
cli = <function cli.<locals>._run at 0x7e71f08a13a0>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=count'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
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
E         stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=count'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_ids_format_space_separated  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e71f17422d0>
cli = <function cli.<locals>._run at 0x7e71f08a0040>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=ids'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
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
E         stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=ids'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_fields_restricts_and_orders_columns  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e71f0da8e60>
cli = <function cli.<locals>._run at 0x7e71f08a1440>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--fields=status,name', '--...t=csv'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
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
E         stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--fields=status,name', '--format=csv'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_fields_case_insensitive  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e71f0dab3b0>
cli = <function cli.<locals>._run at 0x7e71f08a0fe0>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--fields=status,name', '--...t=csv'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
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
E         stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--fields=status,name', '--format=csv'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_json_stdin_supplies_missing_positional_argument  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_confirmation_accepts_trimmed_uppercase_y  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e71f15fbb90>
cli = <function cli.<locals>._run at 0x7e71f08a1260>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
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
E         stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'delete', 'example.test'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_confirmation_blank_response_cancels  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_complex_values_json_serialized_in_table  [FIRST, REGRESSION]
```
self = <test_checkpoint_3.TestFunctionality object at 0x7e71f0da9a90>
cli = <function cli.<locals>._run at 0x7e71f08a1440>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=table'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n')
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
E         stderr: 'Error: Container runtime (docker) is either not installed or not running.\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list', '--format=table'], returncode=1, stdout='', stderr='Error: Container runtime (docker) is either not installed or not running.\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_4.py::TestErrors::test_exit_code_negative_1_warning  [still failing since ck4]

## .evaluation_tests/test_checkpoint_4.py::TestFunctionality::test_non_writable_nested_archive_entry_warns_with_relative_path  [still failing since ck4]

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
<test_checkpoint_6.TestFunctionality object at 0x7e71f0c37380>
cli = <function cli.<locals>._run at 0x7e71f0905ee0>
fake_docker_env = ({'PATH': '/tmp/pytest-of-agent/pytest-0/test_compose_legacy_custom_app0/fake_docker_bin:/tmp/uv-cache/archive-v0/pFOn.../local/games:/usr/games'}, PosixPath('/tmp/pytest-of-agent/pytest-0/test_compose_legacy_custom_app0/docker_calls.log'))
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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', stderr="Error: Unable to determine the version of the compose tool `'docker-compose'`.\n")
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
E         stderr: "Error: Unable to determine the version of the compose tool `'docker-compose'`.\n"
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', stderr="Error: Unable to determine the version of the compose tool `'docker-compose'`.\n").returncode

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

## .evaluation_tests/test_checkpoint_7.py::TestErrors::test_migration_rollback_deletes_records  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestErrors::test_image_pull_failure_error  [still failing since ck7]

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_disk_space_exact_threshold_allows_upgrade  [still failing since ck7]

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', stderr="Error: Unable to determine the version of the compose tool `'docker-compose'`.\n")
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
E         stderr: "Error: Unable to determine the version of the compose tool `'docker-compose'`.\n"
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'site', 'list'], returncode=1, stdout='', stderr="Error: Unable to determine the version of the compose tool `'docker-compose'`.\n").returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestCore::test_version_newer_binary_triggers_migration  [FIRST]
```
self = <test_checkpoint_8.TestCore object at 0x7e71f0cc71d0>
cli = <function cli.<locals>._run at 0x7e71f04a1620>
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
self = <test_checkpoint_8.TestErrors object at 0x7e71f0cc6090>
cli = <function cli.<locals>._run at 0x7e71f04a2200>
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
self = <test_checkpoint_8.TestFunctionality object at 0x7e71f0cc5f40>
cli = <function cli.<locals>._run at 0x7e71f04a23e0>
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
self = <test_checkpoint_8.TestFunctionality object at 0x7e71f0cc7230>
cli = <function cli.<locals>._run at 0x7e71f04a2f20>
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
self = <test_checkpoint_8.TestFunctionality object at 0x7e71f0cc55b0>
cli = <function cli.<locals>._run at 0x7e71f04a3380>

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
E       AssertionError: assert 'version' in {'global_config', 'python_version', 'project_config', 'root_dir', 'shell', 'appctl_stored_version', 'appctl_binary', 'python_path', 'cache_dir', 'appctl_build', 'packages_dir', 'success', 'appctl_version', 'python_binary', 'strict_args_mode', 'os'}

.evaluation_tests/test_checkpoint_8.py:401: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_info_json_format_keys  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x7e71f0cc4fb0>
cli = <function cli.<locals>._run at 0x7e71f04a3420>

    @pytest.mark.functionality
    def test_cli_info_json_format_keys(self, cli):
        """JSON format includes semantic diagnostics.
    
        Spec: key names may differ, semantics must remain available.
        """
        result = cli(["cli", "info", "--format=json"])
        assert_success(result)
        data = json.loads(result.stdout)
        assert isinstance(data, dict)
        lowered = {key.casefold(): value for key, value in data.items()}
        assert any("version" in key for key in lowered)
        assert any("shell" in key for key in lowered)
        assert any("os" in key for key in lowered)
>       assert any("runtime" in key for key in lowered)
E       assert False
E        +  where False = any(<generator object TestFunctionality.test_cli_info_json_format_keys.<locals>.<genexpr> at 0x7e71f05ddf20>)

.evaluation_tests/test_checkpoint_8.py:432: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_check_update_last_filter_wins  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x7e71f0cc5b80>
cli = <function cli.<locals>._run at 0x7e71f04a2e80>

    @pytest.mark.functionality
    def test_cli_check_update_last_filter_wins(self, cli):
        """``--patch --minor`` → minor wins.
    
        Spec: "the last one wins."
        """
        result = cli(["cli", "check-update", "--patch", "--minor"])
>       assert "minor" in (result.stdout + result.stderr).lower()
E       AssertionError: assert 'minor' in 'success: appctl has been set up successfully.\nerror: failed to get latest version (http code 0).\n'
E        +  where 'success: appctl has been set up successfully.\nerror: failed to get latest version (http code 0).\n' = <built-in method lower of str object at 0x7e71f051c1e0>()
E        +    where <built-in method lower of str object at 0x7e71f051c1e0> = ('Success: appctl has been set up successfully.\n' + 'Error: Failed to get latest version (HTTP code 0).\n').lower
E        +      where 'Success: appctl has been set up successfully.\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update', '--patch', '--minor'], returncode=1, stdout='Success: appctl has been set up successfully.\n', stderr='Error: Failed to get latest version (HTTP code 0).\n').stdout
E        +      and   'Error: Failed to get latest version (HTTP code 0).\n' = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update', '--patch', '--minor'], returncode=1, stdout='Success: appctl has been set up successfully.\n', stderr='Error: Failed to get latest version (HTTP code 0).\n').stderr

.evaluation_tests/test_checkpoint_8.py:442: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_check_update_no_updates_success  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x7e71f0cc4920>
cli = <function cli.<locals>._run at 0x7e71f04a27a0>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update'], returncode=1, stdout='Success: appctl has been set up successfully.\n', stderr='Error: Failed to get latest version (HTTP code 0).\n')
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
E         stdout: 'Success: appctl has been set up successfully.\n'
E         stderr: 'Error: Failed to get latest version (HTTP code 0).\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update'], returncode=1, stdout='Success: appctl has been set up successfully.\n', stderr='Error: Failed to get latest version (HTTP code 0).\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_check_update_table_format_no_updates_success  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x7e71f0cc40b0>
cli = <function cli.<locals>._run at 0x7e71f04a22a0>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update', '--format=table'], r...tdout='Success: appctl has been set up successfully.\n', stderr='Error: Failed to get latest version (HTTP code 0).\n')
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
E         stdout: 'Success: appctl has been set up successfully.\n'
E         stderr: 'Error: Failed to get latest version (HTTP code 0).\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update', '--format=table'], returncode=1, stdout='Success: appctl has been set up successfully.\n', stderr='Error: Failed to get latest version (HTTP code 0).\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_check_update_filtered_no_updates_mentions_filter  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x7e71f0cc4170>
cli = <function cli.<locals>._run at 0x7e71f04a2e80>

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

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update', '--patch'], returnco...tdout='Success: appctl has been set up successfully.\n', stderr='Error: Failed to get latest version (HTTP code 0).\n')
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
E         stdout: 'Success: appctl has been set up successfully.\n'
E         stderr: 'Error: Failed to get latest version (HTTP code 0).\n'
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'cli', 'check-update', '--patch'], returncode=1, stdout='Success: appctl has been set up successfully.\n', stderr='Error: Failed to get latest version (HTTP code 0).\n').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_update_requires_confirmation  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x7e71f0cc7d70>
cli = <function cli.<locals>._run at 0x7e71f04a2ca0>

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
E           AssertionError: assert '[y/n]' in 'Success: appctl has been set up successfully.\nError: Failed to get latest version (HTTP code 0).\n'

.evaluation_tests/test_checkpoint_8.py:495: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_param_dump_with_values_reflects_runtime_config  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x7e71f0cc5790>
cli = <function cli.<locals>._run at 0x7e71f04a36a0>
write_config = <function write_config.<locals>._write at 0x7e71f04a19e0>

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
E        +  where None = <built-in method get of dict object at 0x7e71f0a69cc0>('value')
E        +    where <built-in method get of dict object at 0x7e71f0a69cc0> = {'runtime': '[--[no-]color]', 'file': True, 'default': 'auto', 'multiple': False, 'deprecated': False, 'hidden': False, 'desc': 'Whether to colorize the output.', 'current': False}.get

.evaluation_tests/test_checkpoint_8.py:551: AssertionError
```

## .evaluation_tests/test_checkpoint_8.py::TestFunctionality::test_cli_cmd_dump_alphabetical  [FIRST]
```
self = <test_checkpoint_8.TestFunctionality object at 0x7e71f0cc75c0>
cli = <function cli.<locals>._run at 0x7e71f04a1620>

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
> false,\n    'desc' => 'Suppress informational messages.',\n  ),\n  'require' => \n  array (\n    'runtime' => '[--require=<path>]',\n    'file' => true,\n    'default' => NULL,\n    'multiple' => true,\n    'deprecated' => false,\n    'hidden' => false,\n    'desc' => 'Load a file before running the command (may be used more than once).',\n  ),\n  'skip-packages' => \n  array (\n    'runtime' => '[--skip-packages]',\n    'file' => true,\n    'default' => NULL,\n    'multiple' => false,\n    'deprecated' => false,\n    'hidden' => false,\n    'desc' => 'Skip loading all installed packages.',\n  ),\n  'skip-plugins' => \n  array (\n    'runtime' => '[--skip-plugins[=<plugins>]]',\n    'file' => true,\n    'default' => NULL,\n    'multiple' => false,\n    'deprecated' => false,\n    'hidden' => false,\n    'desc' => 'Skip loading all plugins, or a comma-separated list of plugins.',\n  ),\n  'skip-themes' => \n  array (\n    'runtime' => '[--skip-themes[=<themes>]]',\n    'file' => true,\n    'default' => NULL,\n    'multiple' => false,\n    'deprecated' => false,\n    'hidden' => false,\n    'desc' => 'Skip loading all themes, or a comma-separated list of themes.',\n  ),\n  'skip-tty' => \n  array (\n    'runtime' => false,\n    'file' => true,\n    'default' => false,\n    'multiple' => false,\n    'deprecated' => false,\n    'hidden' => false,\n    'desc' => 'Do not allocate a TTY for remote commands.',\n  ),\n  'ssh' => \n  array (\n    'runtime' => '[--ssh=<host>]',\n    'file' => true,\n    'default' => NULL,\n    'multiple' => false,\n    'deprecated' => false,\n    'hidden' => false,\n    'desc' => 'Perform operation against a remote server over SSH (or a container).',\n  ),\n  'sysctl' => \n  array (\n    'runtime' => false,\n    'file' => true,\n    'default' => NULL,\n    'multiple' => false,\n    'deprecated' => false,\n    'hidden' => false,\n    'desc' => 'Kernel parameters applied to containers.',\n  ),\n  'url' => \n  array (\n    'runtime' => '[--url=<url>]',\n    'file' => true,\n    'default' => NULL,\n    'multiple' => false,\n    'deprecated' => false,\n    'hidden' => false,\n    'desc' => 'Pretend request came from given URL.',\n  ),\n  'user' => \n  array (\n    'runtime' => '[--user=<id|login|email>]',\n    'file' => true,\n    'default' => NULL,\n    'multiple' => false,\n    'deprecated' => false,\n    'hidden' => false,\n    'desc' => 'Set the user.',\n  ),\n)".startswith

.evaluation_tests/test_checkpoint_8.py:674: AssertionError
```
