# Checkpoint 5 hidden-test results

Outcomes: {'passed': 131, 'failed': 20}

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

## .evaluation_tests/test_checkpoint_4.py::TestCore::test_detailed_execution_captures_all_fields  [still failing since ck4]

## .evaluation_tests/test_checkpoint_4.py::TestErrors::test_exit_code_negative_1_warning  [still failing since ck4]

## .evaluation_tests/test_checkpoint_5.py::TestCore::test_option_write_insert_then_read  [FIRST]
```
self = <test_checkpoint_5.TestCore object at 0x7cb7220e8290>
cli = <function cli.<locals>._run at 0x7cb721d689a0>
db_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_option_write_insert_then_0/appctl_root/db/appctl.sqlite')

    def test_option_write_insert_then_read(self, cli, db_path):
        """Write new key, read returns value.
    
        Spec: Example 1.
        """
        db_dir = db_path.parent
        cli(["help"])  # Ensure DB is initialized
        conn = _open_store_connection(db_dir)
>       conn.execute(
            "INSERT OR REPLACE INTO options (key, value) VALUES (?, ?)",
            ("test_key", "test_value"),
        )
E       sqlite3.IntegrityError: NOT NULL constraint failed: options.modified_on

.evaluation_tests/test_checkpoint_5.py:116: IntegrityError
```

## .evaluation_tests/test_checkpoint_5.py::TestCore::test_option_upsert_overwrites  [FIRST]
```
self = <test_checkpoint_5.TestCore object at 0x7cb7220e9ee0>
cli = <function cli.<locals>._run at 0x7cb721cf8360>
db_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_option_upsert_overwrites0/appctl_root/db/appctl.sqlite')

    def test_option_upsert_overwrites(self, cli, db_path):
        """Write existing key with new value, read returns new value.
    
        Spec: Example 2.
        """
        db_dir = db_path.parent
        cli(["help"])  # Ensure DB is initialized
        conn = _open_store_connection(db_dir)
>       conn.execute(
            "INSERT OR REPLACE INTO options (key, value) VALUES (?, ?)",
            ("upsert_key", "old_value"),
        )
E       sqlite3.IntegrityError: NOT NULL constraint failed: options.modified_on

.evaluation_tests/test_checkpoint_5.py:137: IntegrityError
```

## .evaluation_tests/test_checkpoint_5.py::TestFunctionality::test_all_values_stored_as_strings  [FIRST]
```
self = <test_checkpoint_5.TestFunctionality object at 0x7cb7220e8980>
cli = <function cli.<locals>._run at 0x7cb721cf8b80>
db_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_all_values_stored_as_stri0/appctl_root/db/appctl.sqlite')

    def test_all_values_stored_as_strings(self, cli, db_path):
        """Stored values round-trip without implicit coercion.
    
        Spec: option values are returned as stored string content.
        """
        db_dir = db_path.parent
        cli(["help"])
        if not any(candidate.is_file() for candidate in db_dir.rglob("*")):
            return
        conn = _open_store_connection(db_dir)
>       conn.execute(
            "INSERT OR REPLACE INTO options (key, value) VALUES (?, ?)",
            ("numeric_test", "42"),
        )
E       sqlite3.IntegrityError: NOT NULL constraint failed: options.modified_on

.evaluation_tests/test_checkpoint_5.py:290: IntegrityError
```

## .evaluation_tests/test_checkpoint_5.py::TestFunctionality::test_empty_string_value_is_not_treated_as_missing  [FIRST]
```
self = <test_checkpoint_5.TestFunctionality object at 0x7cb7220e8ef0>
cli = <function cli.<locals>._run at 0x7cb721cf9120>
db_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_empty_string_value_is_not0/appctl_root/db/appctl.sqlite')

    @pytest.mark.functionality
    def test_empty_string_value_is_not_treated_as_missing(self, cli, db_path):
        """A stored empty string remains distinct from a missing key.
    
        Spec: missing reads return false, while existing keys return the
        stored string value.
        """
        db_dir = db_path.parent
        assert_success(cli(["help"]))
        if not any(candidate.is_file() for candidate in db_dir.rglob("*")):
            return
    
        conn = _open_store_connection(db_dir)
>       conn.execute(
            "INSERT OR REPLACE INTO options (key, value) VALUES (?, ?)",
            ("empty_value_key", ""),
        )
E       sqlite3.IntegrityError: NOT NULL constraint failed: options.modified_on

.evaluation_tests/test_checkpoint_5.py:315: IntegrityError
```

## .evaluation_tests/test_checkpoint_5.py::TestFunctionality::test_parameterized_queries  [FIRST]
```
self = <test_checkpoint_5.TestFunctionality object at 0x7cb7220e8170>
cli = <function cli.<locals>._run at 0x7cb721cf9260>
db_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_parameterized_queries0/appctl_root/db/appctl.sqlite')

    @pytest.mark.functionality
    def test_parameterized_queries(self, cli, db_path):
        """Queries use parameter bindings, not string interpolation.
    
        Spec: "All database queries use parameterized value bindings."
        """
        # Verify by inserting a value with SQL injection attempt
        db_dir = db_path.parent
        cli(["help"])
        if not any(candidate.is_file() for candidate in db_dir.rglob("*")):
            return
        conn = _open_store_connection(db_dir)
        dangerous_key = "'; DROP TABLE options; --"
>       conn.execute(
            "INSERT OR REPLACE INTO options (key, value) VALUES (?, ?)",
            (dangerous_key, "safe"),
        )
E       sqlite3.IntegrityError: NOT NULL constraint failed: options.modified_on

.evaluation_tests/test_checkpoint_5.py:439: IntegrityError
```

## .evaluation_tests/test_checkpoint_5.py::TestFunctionality::test_existing_db_opens_without_recreating  [FIRST]
```
self = <test_checkpoint_5.TestFunctionality object at 0x7cb7220eb7d0>
cli = <function cli.<locals>._run at 0x7cb721cf96c0>
db_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_existing_db_opens_without0/appctl_root/db/appctl.sqlite')

    @pytest.mark.functionality
    def test_existing_db_opens_without_recreating(self, cli, db_path):
        """Existing DB opens connection without recreating tables.
    
        Spec: "If the database file already exists, a connection is opened."
        """
        db_dir = db_path.parent
        # First run creates DB
        cli(["help"])
        if not any(candidate.is_file() for candidate in db_dir.rglob("*")):
            return
        # Insert a marker
        conn = _open_store_connection(db_dir)
>       conn.execute(
            "INSERT OR REPLACE INTO options (key, value) VALUES (?, ?)",
            ("marker", "preserved"),
        )
E       sqlite3.IntegrityError: NOT NULL constraint failed: options.modified_on

.evaluation_tests/test_checkpoint_5.py:510: IntegrityError
```
