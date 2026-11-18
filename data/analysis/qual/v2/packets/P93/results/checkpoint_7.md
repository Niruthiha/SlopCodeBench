# Checkpoint 7 hidden-test results

Outcomes: {'passed': 167, 'failed': 46, 'skipped': 1}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_missing_error  [still failing since ck1]

## .evaluation_tests/test_checkpoint_1.py::TestFunctionality::test_required_associative_empty_value_is_rejected  [still failing since ck1]

## .evaluation_tests/test_checkpoint_2.py::TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::TestErrors::test_invalid_json_stdin_error  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_csv_serializes_complex_values_as_json_strings  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_json_stdin_supplies_missing_positional_argument  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_confirmation_blank_response_cancels  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::TestFunctionality::test_quiet_suppresses_cancellation_warning  [still failing since ck3]

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

## .evaluation_tests/test_checkpoint_6.py::TestErrors::test_network_connect_failure_raises  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_boot_container_exited_starts  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_boot_container_not_exists_creates  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_configured_custom_compose_applies_after_base  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_compose_directory_ignores_non_compose_files_in_call_order  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_missing_custom_compose_warns_and_falls_back_to_base  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_skip_tty_string_truthy_disables_tty  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_service_inspection_lists_names  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_volume_existing_is_silently_skipped  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_network_create_with_label  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_network_disconnect_failure_warning  [still failing since ck6]

## .evaluation_tests/test_checkpoint_6.py::TestFunctionality::test_site_delete_tears_down_containers_networks_and_volumes  [still failing since ck6]

## .evaluation_tests/test_checkpoint_7.py::TestCore::test_migration_discovery_and_ascending_sort  [FIRST]
```
self = <test_checkpoint_7.TestCore object at 0x7e2674e455e0>
cli = <function cli.<locals>._run at 0x7e2674ae4540>
appctl_root = PosixPath('/tmp/pytest-of-agent/pytest-0/test_migration_discovery_and_a0/appctl_root')
db_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_migration_discovery_and_a0/appctl_root/db/appctl.sqlite')

    def test_migration_discovery_and_ascending_sort(
        self, cli, appctl_root, db_path
    ):
        """Pending migrations are discovered and processed deterministically.
    
        Spec: migration discovery/naming is deterministic and package-scoped.
        """
        # Create migration files
        mig_dir = appctl_root / "migrations" / "db"
        mig_dir.mkdir(parents=True, exist_ok=True)
        (mig_dir / "001_core_first.py").write_text(
            "def up(): pass\ndef down(): pass\n"
        )
        (mig_dir / "002_bad_name.py").write_text("this is invalid python")
        (mig_dir / "003_core_third.py").write_text(
            "def up(): pass\ndef down(): pass\n"
        )
    
        cli(["help"])
        rows = (
            sqlite3.connect(db_path)
            .execute("SELECT migration FROM migrations ORDER BY id")
            .fetchall()
        )
        names = [
            row[0]
            for row in rows
            if row[0]
            in {
                "001_core_first.py",
                "003_core_third.py",
                "002_bad_name.py",
            }
        ]
        if names != ["001_core_first.py", "003_core_third.py"]:
>           raise AssertionError(
                f"Expected deterministic sorted migrations, got {names!r}."
            )
E           AssertionError: Expected deterministic sorted migrations, got [].

.evaluation_tests/test_checkpoint_7.py:130: AssertionError
```

## .evaluation_tests/test_checkpoint_7.py::TestCore::test_migration_execution_creates_record  [FIRST]
```
self = <test_checkpoint_7.TestCore object at 0x7e2674e45dc0>
cli = <function cli.<locals>._run at 0x7e2674ae65c0>
appctl_root = PosixPath('/tmp/pytest-of-agent/pytest-0/test_migration_execution_creat0/appctl_root')
db_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_migration_execution_creat0/appctl_root/db/appctl.sqlite')

    def test_migration_execution_creates_record(
        self, cli, appctl_root, db_path
    ):
        """Successful migration creates a migration-history record.
    
        Spec: migration history is persisted.
        """
        mig_dir = appctl_root / "migrations" / "db"
        mig_dir.mkdir(parents=True, exist_ok=True)
        (mig_dir / "001_core_test_migration.py").write_text(
            "def up(): pass\ndef down(): pass\n"
        )
    
        cli(["help"])
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            row = conn.execute(
                """
                SELECT migration, type, timestamp
                FROM migrations
                WHERE migration = ?
                """,
                ("001_core_test_migration.py",),
            ).fetchone()
            conn.close()
            if row is None:
>               raise AssertionError(
                    "Expected successful migration record to be persisted."
                )
E               AssertionError: Expected successful migration record to be persisted.

.evaluation_tests/test_checkpoint_7.py:160: AssertionError
```

## .evaluation_tests/test_checkpoint_7.py::TestCore::test_migration_failure_triggers_batch_rollback  [FIRST]
```
 _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appct...oles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='')
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
E         stdout: "usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n"
E         stderr: ''
E       assert 0 == 1
E        +  where 0 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_7.py::TestErrors::test_migration_rollback_deletes_records  [FIRST]
```
 _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appct...oles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='')
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
E         stdout: "usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n"
E         stderr: ''
E       assert 0 == 1
E        +  where 0 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_7.py::TestErrors::test_image_pull_failure_error  [FIRST]
```
 _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appct...oles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='')
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
E         stdout: "usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n"
E         stderr: ''
E       assert 0 == 1
E        +  where 0 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_disk_space_exact_threshold_allows_upgrade  [FIRST]
```
self = <test_checkpoint_7.TestFunctionality object at 0x7e2674e4f410>
cli = <function cli.<locals>._run at 0x7e2674ae79c0>
appctl_root = PosixPath('/tmp/pytest-of-agent/pytest-0/test_disk_space_exact_threshol0/appctl_root')
db_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_disk_space_exact_threshol0/appctl_root/db/appctl.sqlite')
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_disk_space_exact_threshol0')

    @pytest.mark.functionality
    def test_disk_space_exact_threshold_allows_upgrade(
        self, cli, appctl_root, db_path, tmp_path
    ):
        """At exactly 5 GiB free, upgrade work may proceed.
    
        Spec: "At least 5 GiB must be available" before upgrade mutation begins.
        """
        mig_dir = appctl_root / "migrations" / "db"
        mig_dir.mkdir(parents=True, exist_ok=True)
        migration_name = "001_core_exact_threshold.py"
        (mig_dir / migration_name).write_text(
            "def up(): pass\ndef down(): pass\n"
        )
    
        result = cli(
            ["help"],
            env=_disk_usage_env(
                tmp_path,
                root_free_bytes=MIN_DISK_SPACE_BYTES,
                runtime_free_bytes=MIN_DISK_SPACE_BYTES,
            ),
        )
        assert_success(result)
    
        conn = sqlite3.connect(str(db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM migrations WHERE migration = ?",
            (migration_name,),
        ).fetchone()[0]
        conn.close()
        if count != 1:
>           raise AssertionError(
                f"Expected migration to run at the 5 GiB boundary, got {count} rows."
            )
E           AssertionError: Expected migration to run at the 5 GiB boundary, got 0 rows.

.evaluation_tests/test_checkpoint_7.py:381: AssertionError
```

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_runtime_disk_space_failure_blocks_upgrade_mutations  [FIRST]
```
 _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appct...oles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='')
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
E         stdout: "usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n"
E         stderr: ''
E       assert 0 == 1
E        +  where 0 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_rollback_strict_reverse_order  [FIRST]
```
 _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appct...oles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='')
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
E         stdout: "usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n"
E         stderr: ''
E       assert 0 == 1
E        +  where 0 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_rollback_undo_failure_logged_continues  [FIRST]
```
 _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appct...oles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='')
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
E         stdout: "usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n"
E         stderr: ''
E       assert 0 == 1
E        +  where 0 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_rollback_no_undo_skipped  [FIRST]
```
 _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appct...oles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='')
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
E         stdout: "usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n"
E         stderr: ''
E       assert 0 == 1
E        +  where 0 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='').returncode

.evaluation_tests/conftest.py:314: AssertionError
```

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_no_pending_migrations_do_not_duplicate_history  [FIRST]
```
self = <test_checkpoint_7.TestFunctionality object at 0x7e2674e4ea50>
cli = <function cli.<locals>._run at 0x7e2674ae7c40>
appctl_root = PosixPath('/tmp/pytest-of-agent/pytest-0/test_no_pending_migrations_do_0/appctl_root')
db_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_no_pending_migrations_do_0/appctl_root/db/appctl.sqlite')

    @pytest.mark.functionality
    def test_no_pending_migrations_do_not_duplicate_history(
        self, cli, appctl_root, db_path
    ):
        """When no migrations are pending, reruns stay silent and idempotent.
    
        Spec: "Migrations already present in migration history must be
        excluded." and "If there are no pending migrations, the tool must
        continue silently."
        """
        mig_dir = appctl_root / "migrations" / "db"
        mig_dir.mkdir(parents=True, exist_ok=True)
        migration_name = "001_core_no_pending.py"
        (mig_dir / migration_name).write_text(
            "def up(): pass\ndef down(): pass\n"
        )
    
        first_result = cli(["help"])
        assert_success(first_result)
    
        conn = sqlite3.connect(str(db_path))
        first_count = conn.execute(
            "SELECT COUNT(*) FROM migrations WHERE migration = ?",
            (migration_name,),
        ).fetchone()[0]
        conn.close()
        if first_count != 1:
>           raise AssertionError(
                f"Expected one migration history row after first run, got {first_count}."
            )
E           AssertionError: Expected one migration history row after first run, got 0.

.evaluation_tests/test_checkpoint_7.py:637: AssertionError
```

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_container_migrations_after_db_migrations  [FIRST]
```
self = <test_checkpoint_7.TestFunctionality object at 0x7e2674e4e810>
cli = <function cli.<locals>._run at 0x7e2674ae5260>
appctl_root = PosixPath('/tmp/pytest-of-agent/pytest-0/test_container_migrations_afte0/appctl_root')
db_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_container_migrations_afte0/appctl_root/db/appctl.sqlite')

    @pytest.mark.functionality
    def test_container_migrations_after_db_migrations(
        self, cli, appctl_root, db_path
    ):
        """Container migrations run after DB migrations.
    
        Spec: "run after database migrations and before container image upgrades."
        """
        db_mig = appctl_root / "migrations" / "db"
        db_mig.mkdir(parents=True, exist_ok=True)
        (db_mig / "001_core_db_mig.py").write_text(
            "def up(): pass\ndef down(): pass\n"
        )
    
        container_mig = appctl_root / "migrations" / "container"
        container_mig.mkdir(parents=True, exist_ok=True)
        (container_mig / "001_core_container_mig.py").write_text(
            "def up(): pass\ndef down(): pass\n"
        )
    
        result = cli(["help"])
        assert_success(result)
        # Both migration sources should have been processed
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute("SELECT migration FROM migrations").fetchall()
            conn.close()
            names = [r[0] for r in rows]
            if "001_core_db_mig.py" not in names:
>               raise AssertionError("DB migration must be recorded.")
E               AssertionError: DB migration must be recorded.

.evaluation_tests/test_checkpoint_7.py:688: AssertionError
```

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_image_pulls_sequential  [FIRST]
```
self = <test_checkpoint_7.TestFunctionality object at 0x7e2674e4e450>
cli = <function cli.<locals>._run at 0x7e2674ae68e0>
fake_docker_env = ({'PATH': '/tmp/pytest-of-agent/pytest-0/test_image_pulls_sequential0/fake_docker_bin:/tmp/uv-cache/archive-v0/c_4opem...usr/local/games:/usr/games'}, PosixPath('/tmp/pytest-of-agent/pytest-0/test_image_pulls_sequential0/docker_calls.log'))
appctl_root = PosixPath('/tmp/pytest-of-agent/pytest-0/test_image_pulls_sequential0/appctl_root')

    @pytest.mark.functionality
    def test_image_pulls_sequential(self, cli, fake_docker_env, appctl_root):
        """Images pulled one at a time, not concurrent.
    
        Spec: "sequential -- one image at a time."
        """
        docker_env, log_file = fake_docker_env
        cli(["help"], env=docker_env)
        pulls = [
            line
            for line in log_file.read_text().splitlines()
            if "docker pull" in line or "pull" in line.lower()
        ]
        if len(pulls) < 1:
>           raise AssertionError("At least one image pull must occur.")
E           AssertionError: At least one image pull must occur.

.evaluation_tests/test_checkpoint_7.py:704: AssertionError
```

## .evaluation_tests/test_checkpoint_7.py::TestFunctionality::test_container_migration_failure_blocks_image_pulls  [FIRST]
```
 _ _ _ _ _ _ _ 

result = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appct...oles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='')
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
E         stdout: "usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n"
E         stderr: ''
E       assert 0 == 1
E        +  where 0 = CompletedProcess(args=['/usr/local/bin/uv', 'run', '/workspace/appctl.py', 'help'], returncode=0, stdout="usage: appctl <command> [<subcommand>] [<args>] [--<flags>]\n\nManage applications from the command line.\n\nAvailable commands:\n\n  cache   Add, remove, fetch, and flush the object cache.\n  cli     Review current appctl info, check for updates, or see defined aliases.\n  config  Generate and read the application configuration file.\n  db      Perform basic database operations.\n  help    Get help on appctl, or on a specific command.\n  option  Retrieve and set site options.\n  plugin  Manage plugins.\n  post    Manage posts, content, and meta.\n  site    Create, delete, list, and update sites.\n  theme   Manage themes.\n  user    Manage users, along with their roles, capabilities, and meta.\n\nSee 'appctl help <command>' for more information on a specific command.\n", stderr='').returncode

.evaluation_tests/conftest.py:314: AssertionError
```
