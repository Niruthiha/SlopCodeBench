# Failure summary: runs/recli/c1_default_s1_20261110T2051

## checkpoint_1
pass {'Core': 11, 'Functionality': 15, 'Regression': 0, 'Error': 6} / total {'Core': 11, 'Functionality': 17, 'Regression': 0, 'Error': 6}

**checkpoint_1-Functionality** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**Agent final message:** I've built `appctl.py` in `/workspace`. I ran each behaviour in the spec by hand and every one produced the expected output and exit code; there is no automated test suite. It uses only the Python standard library, so `requirements.txt` lists no dependencies. The virtual environment is in `.venv`.

**The command set is my own invention.** The spec only names `site create`, `cli version` and `help`, so I modelled the rest on WP-CLI. The top-level commands are `cache`, `cli`, `config`, `db`, `help`, `option`, `plugin`, `post`, `site`, `theme` and `user`, each with subcommands, and some go three levels deep (`site meta get`, `cli alias add`). If your tests expect particular commands, arguments or output wording, those parts may not match even though the dispatch and validation rules do. The command handlers only print sample data and success messages; they don't store anything.

**What I checked:**
- **Help:** no arguments prints every top-level command with its description in aligned columns, sorted ignoring case, and exits 0. `<cmd> --help` becomes `help <cmd>`, and `--version` becomes `cli version`.
- **Groups:** running a group with no handler of its own (like `appctl site`) prints the usage line of each subcommand.
- **Unknown commands:** an unknown command or subcommand prints the exact error from the spec to STDERR and exits 1. A "Did you mean" line follows when there is a close match: a name within two typing edits, or a curated synonym such as `new` → `create` or `remov

## checkpoint_2
pass {'Core': 9, 'Functionality': 22, 'Regression': 32, 'Error': 5} / total {'Core': 9, 'Functionality': 23, 'Regression': 34, 'Error': 5}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Functionality** (1 failed)
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 

**Agent final message:** I've implemented the configuration system, aliases and global parameters in `appctl.py`, and every spec example and error message matches when I run it. There are no new dependencies, so `requirements.txt` is unchanged. PyYAML wasn't installed, and real alias configs often use unquoted `@name:` keys, which standard YAML rejects. So I wrote a small built-in YAML reader instead; I'd briefly installed PyYAML in the venv and then removed it.

**What I checked by running it:**
- **Config precedence:** runtime flags beat the project config, which beats the global config, which beats the defaults. The project file is found by searching upward, with `appctl.local.yml` preferred over `appctl.yml`. Inheritance (`_: inherit`) and array appending (`_: merge`) work, and a file that inherits itself doesn't loop forever.
- **Auto-creation:** `locale: en_US` and `installer_version: stable` are added to the global config if missing. If the file can't be written, the tool exits 1 with an error.
- **Disabled commands:** running one gives the exact error and exit 1. They're also hidden from help listings, and `cli has-command` reports them as missing.
- **Aliases:** all the alias errors match the spec (including the "Did you mean" suggestion), `@all` runs in case-insensitive alphabetical order, groups skip duplicates, and runtime aliases override file aliases. Relative paths are resolved from the config file's folder.
- **Remote execution:** I tested with a fake `ssh` script, because `ssh` isn't

## checkpoint_3
pass {'Core': 7, 'Functionality': 19, 'Regression': 68, 'Error': 3} / total {'Core': 7, 'Functionality': 23, 'Regression': 71, 'Error': 4}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (1 failed)
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 

**checkpoint_3-Error** (1 failed)
- `TestErrors::test_invalid_json_stdin_error`: 

**checkpoint_3-Functionality** (4 failed)
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 
- `TestFunctionality::test_quiet_suppresses_cancellation_warning`: 

**Agent final message:** I've added the output, logging and prompt features to `appctl.py`, and I ran each feature by hand against the CLI. There's no automated test suite, so those manual runs are all the checking that's been done. Everything uses the standard library, so `requirements.txt` is unchanged.

**What now works:**
- **Output formats:** all six formats work. JSON is indented 4 spaces. Arrays and objects appear as JSON strings in table and CSV output. CSV uses the same column order as the table. When there's exactly one result, the table switches to a vertical Field/Value layout.
- **Field selection:** `--field` and `--fields` match names case-insensitively and accept a per-command prefix, so `--field=title` finds `post_title`. A bad name prints `Error: Invalid field: <name>.` and exits with code 1.
- **Messages:** each message type goes to the stream the spec requires. `Error:` is red, `Warning:` yellow, `Success:` green and `Debug:` blue. Color follows `--color`, `--no-color` or the `color` config key; in auto mode it's on only when STDOUT is a terminal and the system isn't Windows.
- **Debug:** each line shows the time since start, e.g. `(0.012s)`. With a group, as in `--debug=commands`, only that group's messages appear, labelled `Debug (commands):`.
- **Log file:** every run writes to `<APPCTL_ROOT_DIR>/logs/appctl.log`, starting with a `====` line and the command. Every line carries a UTC timestamp like `[2026-11-11T02:14:10Z]`. Success messages are never logged. Tab completion runs w

## checkpoint_4
pass {'Core': 4, 'Functionality': 18, 'Regression': 97, 'Error': 3} / total {'Core': 5, 'Functionality': 19, 'Regression': 105, 'Error': 4}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (1 failed)
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 

**checkpoint_3-Regression** (5 failed)
- `TestErrors::test_invalid_json_stdin_error`: 
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 
- `TestFunctionality::test_quiet_suppresses_cancellation_warning`: 

**checkpoint_4-Core** (1 failed)
- `TestCore::test_detailed_execution_captures_all_fields`: 

**checkpoint_4-Error** (1 failed)
- `TestErrors::test_exit_code_negative_1_warning`: 

**checkpoint_4-Functionality** (1 failed)
- `TestFunctionality::test_non_writable_nested_archive_entry_warns_with_relative_path`: 

**Agent final message:** I've added all three parts of the spec to `appctl.py`. They use only the Python standard library, so `requirements.txt` stays unchanged. I tested by hand with scratch scripts; I didn't add test files, and I didn't run any existing test suite (I didn't find one).

**Command execution**
- **Detailed run:** `run_detailed()` (or `Process.create(...).run()`) returns stdout, stderr, the return code and elapsed time. It logs the command at debug level first, then any non-empty stdout and stderr, then the return code. `launch()` wraps it with options to exit on failure or return the full result.
- **Success only:** `run_success()` returns whether the command succeeded and logs it the same way.
- **Masking secrets:** every function takes an `obfuscate` list, and each listed string shows as `******` in the debug log. I also mask it in the logged stdout and stderr, not just the command line. The command still runs with the real value, and the returned result keeps the real outputs.
- **Exit code -1:** this prints a warning about signal handling configuration to STDERR and execution carries on.
- **Re-running the tool:** `launch_self()` and `runcommand()` run `appctl.py` again as a child process. They pass along the global config file path and the global flags from the current run. `parse="json"` turns the child's stdout into JSON; if it isn't valid JSON you get `None` rather than an error.

**File cache (`FileCache`)**
- **Location:** `APPCTL_CACHE_DIR` if set, otherwise `<APPCTL_ROOT_D

## checkpoint_5
pass {'Core': 2, 'Functionality': 8, 'Regression': 122, 'Error': 2} / total {'Core': 5, 'Functionality': 11, 'Regression': 133, 'Error': 2}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (1 failed)
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 

**checkpoint_3-Regression** (5 failed)
- `TestErrors::test_invalid_json_stdin_error`: 
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 
- `TestFunctionality::test_quiet_suppresses_cancellation_warning`: 

**checkpoint_4-Regression** (3 failed)
- `TestCore::test_detailed_execution_captures_all_fields`: 
- `TestErrors::test_exit_code_negative_1_warning`: 
- `TestFunctionality::test_non_writable_nested_archive_entry_warns_with_relative_path`: 

**checkpoint_5-Core** (3 failed)
- `TestCore::test_option_upsert_overwrites`: 
- `TestCore::test_option_write_insert_then_read`: 
- `TestFunctionality::test_all_values_stored_as_strings`: 

**checkpoint_5-Functionality** (3 failed)
- `TestFunctionality::test_empty_string_value_is_not_treated_as_missing`: 
- `TestFunctionality::test_existing_db_opens_without_recreating`: 
- `TestFunctionality::test_parameterized_queries`: 

**Agent final message:** I added the persistent store to `appctl.py`, in a new "Persistent state database" section. Every command except tab completion now opens or creates it at startup. I checked it with throwaway scripts and command runs, not a test suite, and I deleted the temporary files afterwards.

**Where it lives:** `<APPCTL_ROOT_DIR>/db/appctl.sqlite`. The `db/` folder and the file are created the first time they're needed. It has two tables:
- `options`: a `key`, a `value` and a `modified_on` time.
- `migrations`: an `id`, the migration name, its category (`type`) and the time it was applied (`timestamp`).

**What I checked:**
- **Settings:** reading a key returns its stored string, and reading a missing key returns `False` with no error. Writing an existing key updates it in place. Values are always stored as strings: `5` becomes `"5"`, `True` becomes `"1"`, and `None` and `False` become `""`.
- **Untrusted values:** all queries pass values separately from the SQL text. A key like `x'; DROP TABLE options;--` was stored as ordinary text.
- **Migrations:** they run in name order and skip any already recorded. A record is written only after a migration succeeds; if one fails, its undo step runs and its record is removed. Rolling one back also removes its record.
- **Ordering and timestamps:** lists come back sorted (settings by key, migrations by name). Times use the form `2026-11-11T02:22:59Z`.
- **Connection errors:** if `db` is a file, or the database path is a folder, the tool prints `Er

## checkpoint_6
pass {'Core': 0, 'Functionality': 11, 'Regression': 134, 'Error': 1} / total {'Core': 6, 'Functionality': 24, 'Regression': 151, 'Error': 3}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (1 failed)
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 

**checkpoint_3-Regression** (5 failed)
- `TestErrors::test_invalid_json_stdin_error`: 
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 
- `TestFunctionality::test_quiet_suppresses_cancellation_warning`: 

**checkpoint_4-Regression** (3 failed)
- `TestCore::test_detailed_execution_captures_all_fields`: 
- `TestErrors::test_exit_code_negative_1_warning`: 
- `TestFunctionality::test_non_writable_nested_archive_entry_warns_with_relative_path`: 

**checkpoint_5-Regression** (6 failed)
- `TestCore::test_option_upsert_overwrites`: 
- `TestCore::test_option_write_insert_then_read`: 
- `TestFunctionality::test_all_values_stored_as_strings`: 
- `TestFunctionality::test_empty_string_value_is_not_treated_as_missing`: 
- `TestFunctionality::test_existing_db_opens_without_recreating`: 
- `TestFunctionality::test_parameterized_queries`: 

**checkpoint_6-Core** (6 failed)
- `TestCore::test_compose_merge_base_always_first`: 
- `TestCore::test_container_status_exited`: 
- `TestCore::test_container_status_false_not_exists`: 
- `TestCore::test_container_status_running`: 
- `TestCore::test_project_naming_prefix`: 
- `TestCore::test_volume_creation_with_labels`: 

**checkpoint_6-Error** (2 failed)
- `TestErrors::test_container_runtime_not_installed_error`: 
- `TestErrors::test_network_connect_failure_raises`: 

**checkpoint_6-Functionality** (13 failed)
- `TestFunctionality::test_boot_container_exited_starts`: 
- `TestFunctionality::test_boot_container_not_exists_creates`: 
- `TestFunctionality::test_boot_container_running_noop`: 
- `TestFunctionality::test_compose_directory_ignores_non_compose_files_in_call_order`: 
- `TestFunctionality::test_configured_custom_compose_applies_after_base`: 
- `TestFunctionality::test_missing_custom_compose_warns_and_falls_back_to_base`: 
- `TestFunctionality::test_network_create_with_label`: 
- `TestFunctionality::test_network_disconnect_failure_warning`: 
- `TestFunctionality::test_service_inspection_lists_names`: 
- `TestFunctionality::test_site_delete_tears_down_containers_networks_and_volumes`: 
- `TestFunctionality::test_skip_tty_flag_passed`: 
- `TestFunctionality::test_skip_tty_string_truthy_disables_tty`: 
- `TestFunctionality::test_volume_existing_is_silently_skipped`: 

**Agent final message:** The spec is implemented in `appctl.py`. I checked it two ways: the new `site config` command on sample projects, and the container, volume and network functions against a fake `docker` binary that logged every call. No real containers were run, because the Docker daemon isn't running here. `requirements.txt` doesn't change since everything uses the standard library.

**The `site config --services` command**
- It prints service names one per line, in the order they appear in the merged compose files. I read the files myself rather than calling `docker compose config --services`, because Docker sorts the names alphabetically.
- It finds the project from the site name (under `projects_path`), from `--path`, or by searching upward from the current directory.
- Without `--services` it prints the whole merged configuration as YAML.

**Merging compose files**
- The base file is found under the usual names (`docker-compose.yml`, `compose.yml`, and their `.yaml` versions).
- If `custom-compose` is set (in a config file or as `--custom-compose` on the command), it is applied after the base file and replaces any other overrides.
- If that custom file doesn't exist, the tool prints `Warning: File: <path> does not exist. Falling back to default compose file.` to STDERR and carries on.
- When no custom file is set, it picks up `docker-compose.override.yml` and then the files in a `user-docker-compose/` folder, sorted by name.
- Anything that isn't a compose file is skipped: wrong file exte

## checkpoint_7
pass {'Core': 2, 'Functionality': 12, 'Regression': 151, 'Error': 2} / total {'Core': 5, 'Functionality': 21, 'Regression': 184, 'Error': 4}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (1 failed)
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 

**checkpoint_3-Regression** (5 failed)
- `TestErrors::test_invalid_json_stdin_error`: 
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 
- `TestFunctionality::test_quiet_suppresses_cancellation_warning`: 

**checkpoint_4-Regression** (2 failed)
- `TestErrors::test_exit_code_negative_1_warning`: 
- `TestFunctionality::test_non_writable_nested_archive_entry_warns_with_relative_path`: 

**checkpoint_5-Regression** (6 failed)
- `TestCore::test_option_upsert_overwrites`: 
- `TestCore::test_option_write_insert_then_read`: 
- `TestFunctionality::test_all_values_stored_as_strings`: 
- `TestFunctionality::test_empty_string_value_is_not_treated_as_missing`: 
- `TestFunctionality::test_existing_db_opens_without_recreating`: 
- `TestFunctionality::test_parameterized_queries`: 

**checkpoint_6-Regression** (16 failed)
- `TestCore::test_compose_merge_base_always_first`: 
- `TestCore::test_project_naming_prefix`: 
- `TestCore::test_volume_creation_with_labels`: 
- `TestErrors::test_container_runtime_not_installed_error`: 
- `TestErrors::test_network_connect_failure_raises`: 
- `TestFunctionality::test_boot_container_exited_starts`: 
- `TestFunctionality::test_boot_container_not_exists_creates`: 
- `TestFunctionality::test_compose_directory_ignores_non_compose_files_in_call_order`: 
- `TestFunctionality::test_configured_custom_compose_applies_after_base`: 
- `TestFunctionality::test_missing_custom_compose_warns_and_falls_back_to_base`: 
- `TestFunctionality::test_network_create_with_label`: 
- `TestFunctionality::test_network_disconnect_failure_warning`: 
- `TestFunctionality::test_service_inspection_lists_names`: 
- `TestFunctionality::test_site_delete_tears_down_containers_networks_and_volumes`: 
- `TestFunctionality::test_skip_tty_string_truthy_disables_tty`: 
- `TestFunctionality::test_volume_existing_is_silently_skipped`: 

**checkpoint_7-Core** (3 failed)
- `TestCore::test_migration_discovery_and_ascending_sort`: 
- `TestCore::test_migration_execution_creates_record`: 
- `TestCore::test_migration_failure_triggers_batch_rollback`: 

**checkpoint_7-Error** (2 failed)
- `TestErrors::test_image_pull_failure_error`: 
- `TestErrors::test_migration_rollback_deletes_records`: 

**checkpoint_7-Functionality** (9 failed)
- `TestFunctionality::test_container_migration_failure_blocks_image_pulls`: 
- `TestFunctionality::test_container_migrations_after_db_migrations`: 
- `TestFunctionality::test_disk_space_exact_threshold_allows_upgrade`: 
- `TestFunctionality::test_image_pulls_sequential`: 
- `TestFunctionality::test_no_pending_migrations_do_not_duplicate_history`: 
- `TestFunctionality::test_rollback_no_undo_skipped`: 
- `TestFunctionality::test_rollback_strict_reverse_order`: 
- `TestFunctionality::test_rollback_undo_failure_logged_continues`: 
- `TestFunctionality::test_runtime_disk_space_failure_blocks_upgrade_mutations`: 

**Agent final message:** I've added the upgrade system to `appctl.py`. It only uses the Python standard library, so `requirements.txt` didn't need to change. I tested it against a fake `docker` that records every call and can be made to fail on purpose. I didn't run it against a real container daemon, because there isn't one running here.

**When it runs:** at startup, if the stored `version` option doesn't match the tool's version, or if any migrations are still pending. If neither is true, it does nothing and prints nothing. After an upgrade succeeds, the command you typed runs as usual.

**Order of work:**
1. **Disk space check, before anything changes:** at least 5 GiB free on the filesystem holding the tool's root directory, and on the one holding Docker's data directory. If either fails, it prints `...minimum 5GB disk space is required...` to stderr and exits with code 1.
2. **Compose tool:** if its version is below 2.0.0 (semantic versioning), it downloads the new one, checks it works, backs up the old one and swaps it in. If anything in that fails, the old binary is put back, a warning is shown and the upgrade carries on.
3. **Database migrations, then container migrations:** they run in ascending order and each success is recorded in the `migrations` table. If one fails, it and every migration before it in the batch are undone newest-first and their records deleted.
4. **Images:** each image whose target tag differs exactly from the recorded one is pulled, one at a time. A failure reports `U

## checkpoint_8
pass {'Core': 5, 'Functionality': 19, 'Regression': 138, 'Error': 2} / total {'Core': 7, 'Functionality': 31, 'Regression': 214, 'Error': 3}

**checkpoint_1-Regression** (12 failed)
- `TestCore::test_help_rewrite`: 
- `TestCore::test_help_rewrite_for_multi_level_command`: 
- `TestErrors::test_excess_positional_args_error`: 
- `TestErrors::test_missing_required_positional_shows_usage`: 
- `TestErrors::test_multiple_parameter_errors_collected`: 
- `TestErrors::test_unknown_associative_no_suggestion`: 
- `TestErrors::test_unknown_associative_with_suggestion`: 
- `TestErrors::test_unrecognized_subcommand_error`: 
- `TestFunctionality::test_parent_command_no_handler_shows_subcommands`: 
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 
- `TestFunctionality::test_subcommand_synonym_example_allows_optional_delete_suggestion`: 

**checkpoint_2-Regression** (6 failed)
- `TestCore::test_disabled_command_error`: 
- `TestFunctionality::test_project_config_local_yml_priority_overrides_project_disabled_command`: 
- `TestFunctionality::test_project_config_search_stops_at_first_matching_directory`: 
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 
- `TestFunctionality::test_yaml_merge_arrays_appended`: 
- `TestFunctionality::test_yaml_merge_arrays_not_deduplicated`: 

**checkpoint_3-Regression** (19 failed)
- `TestCore::test_field_single_value_raw_output`: 
- `TestCore::test_json_format_4_space_indent`: 
- `TestCore::test_table_format_default`: 
- `TestErrors::test_confirmation_prompt_non_y_aborts`: 
- `TestErrors::test_invalid_field_name_error`: 
- `TestErrors::test_invalid_fields_plural_error`: 
- `TestErrors::test_invalid_json_stdin_error`: 
- `TestFunctionality::test_complex_values_json_serialized_in_table`: 
- `TestFunctionality::test_confirmation_accepts_trimmed_uppercase_y`: 
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_count_format_integer`: 
- `TestFunctionality::test_csv_format_quoting`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_fields_case_insensitive`: 
- `TestFunctionality::test_fields_restricts_and_orders_columns`: 
- `TestFunctionality::test_formats_preserve_same_underlying_values`: 
- `TestFunctionality::test_ids_format_space_separated`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 
- `TestFunctionality::test_yaml_format_output`: 

**checkpoint_4-Regression** (2 failed)
- `TestErrors::test_exit_code_negative_1_warning`: 
- `TestFunctionality::test_non_writable_nested_archive_entry_warns_with_relative_path`: 

**checkpoint_5-Regression** (6 failed)
- `TestCore::test_option_upsert_overwrites`: 
- `TestCore::test_option_write_insert_then_read`: 
- `TestFunctionality::test_all_values_stored_as_strings`: 
- `TestFunctionality::test_empty_string_value_is_not_treated_as_missing`: 
- `TestFunctionality::test_existing_db_opens_without_recreating`: 
- `TestFunctionality::test_parameterized_queries`: 

**checkpoint_6-Regression** (16 failed)
- `TestCore::test_compose_merge_base_always_first`: 
- `TestCore::test_project_naming_prefix`: 
- `TestCore::test_volume_creation_with_labels`: 
- `TestErrors::test_container_runtime_not_installed_error`: 
- `TestFunctionality::test_boot_container_exited_starts`: 
- `TestFunctionality::test_boot_container_not_exists_creates`: 
- `TestFunctionality::test_compose_directory_ignores_non_compose_files_in_call_order`: 
- `TestFunctionality::test_compose_legacy_custom_appended_last`: 
- `TestFunctionality::test_configured_custom_compose_applies_after_base`: 
- `TestFunctionality::test_missing_custom_compose_warns_and_falls_back_to_base`: 
- `TestFunctionality::test_network_create_with_label`: 
- `TestFunctionality::test_network_disconnect_failure_warning`: 
- `TestFunctionality::test_service_inspection_lists_names`: 
- `TestFunctionality::test_site_delete_tears_down_containers_networks_and_volumes`: 
- `TestFunctionality::test_skip_tty_string_truthy_disables_tty`: 
- `TestFunctionality::test_volume_existing_is_silently_skipped`: 

**checkpoint_7-Regression** (14 failed)
- `TestCore::test_migration_discovery_and_ascending_sort`: 
- `TestCore::test_migration_execution_creates_record`: 
- `TestCore::test_migration_failure_triggers_batch_rollback`: 
- `TestErrors::test_image_pull_failure_error`: 
- `TestErrors::test_migration_rollback_deletes_records`: 
- `TestFunctionality::test_container_migration_failure_blocks_image_pulls`: 
- `TestFunctionality::test_container_migrations_after_db_migrations`: 
- `TestFunctionality::test_disk_space_exact_threshold_allows_upgrade`: 
- `TestFunctionality::test_image_pulls_sequential`: 
- `TestFunctionality::test_no_pending_migrations_do_not_duplicate_history`: 
- `TestFunctionality::test_rollback_no_undo_skipped`: 
- `TestFunctionality::test_rollback_strict_reverse_order`: 
- `TestFunctionality::test_rollback_undo_failure_logged_continues`: 
- `TestFunctionality::test_runtime_disk_space_failure_blocks_upgrade_mutations`: 

**checkpoint_8-Core** (2 failed)
- `TestCore::test_sysreq_exponential_backoff_retries`: 
- `TestCore::test_version_newer_binary_triggers_migration`: 

**checkpoint_8-Error** (1 failed)
- `TestErrors::test_older_binary_non_cli_error`: 

**checkpoint_8-Functionality** (12 failed)
- `TestFunctionality::test_cli_check_update_filtered_no_updates_mentions_filter`: 
- `TestFunctionality::test_cli_check_update_last_filter_wins`: 
- `TestFunctionality::test_cli_check_update_no_updates_success`: 
- `TestFunctionality::test_cli_check_update_table_format_no_updates_success`: 
- `TestFunctionality::test_cli_cmd_dump_alphabetical`: 
- `TestFunctionality::test_cli_info_json_format_keys`: 
- `TestFunctionality::test_cli_info_list_format_field_order`: 
- `TestFunctionality::test_cli_param_dump_var_export_output`: 
- `TestFunctionality::test_cli_param_dump_with_values_reflects_runtime_config`: 
- `TestFunctionality::test_cli_update_requires_confirmation`: 
- `TestFunctionality::test_older_binary_cli_warning`: 
- `TestFunctionality::test_runtime_binary_resolution_precedence`: 

**Agent final message:** I've extended the existing `appctl.py` to cover the whole spec; it still uses only the standard library, so `requirements.txt` is unchanged. There's no test suite in the repo, so I checked each feature by hand: fake `docker`/`docker-compose` scripts, a local HTTP server standing in for the releases API, a pty for the interactive cases, and patching `sys.platform` to simulate macOS. All of those runs behaved as intended. A diff against the original file showed only the intended changes.

**What's in place**
- **Requirement checks:** these run before every command outside `cli`, `config` and `help`.
  - Docker must answer `docker ps` or `docker info`. A failed check is retried with doubling waits (about 3.5s in total) before it gives up.
  - The compose tool must be at least 2.0.0. The standalone `docker-compose` is checked first, then the `docker compose` plugin.
  - Python must be at least 3.8.
  - Every failure is reported on STDERR and the exit code is 1. On macOS the Docker error adds `brew install --cask docker`.
- **First run:** creates the database, runs pending migrations and prints a success line on STDOUT, plus setup steps on macOS. The success line is left out for machine-readable output, such as `--format=json`/csv/yaml/count, `--field`, `--porcelain`, `cli version`, `cmd-dump` and `param-dump`. `has-command` prints nothing at all.
- **Version on startup:** a newer binary migrates. An older binary gives a warning for `cli` commands and an error with exit 1 for ever
