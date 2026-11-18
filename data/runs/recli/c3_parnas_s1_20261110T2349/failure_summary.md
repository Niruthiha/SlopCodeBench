# Failure summary: runs/recli/c3_parnas_s1_20261110T2349

## checkpoint_1
pass {'Core': 11, 'Functionality': 15, 'Regression': 0, 'Error': 6} / total {'Core': 11, 'Functionality': 17, 'Regression': 0, 'Error': 6}

**checkpoint_1-Functionality** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**Agent final message:** I've built `appctl.py` and its supporting modules, and all 25 tests in the pytest suite pass. A manual run of every case in the spec's error table gives the specified message, output stream and exit code.

**Running it**
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python appctl.py site create foo
.venv/bin/pytest
```
The tool needs only the Python standard library. `requirements.txt` lists just `pytest`, for the tests.

**Design by information hiding** (full table in `DESIGN.md`). Each module in `appctl_core/` owns one decision, and modules talk to each other only through methods, strings or fresh copies, never through each other's internal data:

| Module | Secret |
|---|---|
| `tokens` | How raw argv is split into `--key=value`, `--flag` and positional words (including `--`). |
| `rewrites` | Which shortcuts are rewritten: `<cmd> --help` → `help <cmd>`, a bare `--version` → `cli version`. |
| `runtime_config` | Which global parameters exist, which env var turns on strict mode, and where in argv globals may appear. |
| `synopsis` | How synopsis strings are parsed and each part classified (positional, keyed, flag, `--[no-]` flag, generic `--<field>=<value>`, malformed, optional `[...]`, repeating `...`). |
| `binding` | The order of argument checks, what counts as an error, how errors are batched under `Parameter errors:`, and when defaults are filled in. |
| `suggest` / `synonyms` | How the single "Did you mean" candidate is picked (edit 

## checkpoint_2
pass {'Core': 8, 'Functionality': 22, 'Regression': 32, 'Error': 5} / total {'Core': 9, 'Functionality': 23, 'Regression': 34, 'Error': 5}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Core** (1 failed)
- `TestCore::test_config_runtime_overrides_project`: 

**checkpoint_2-Functionality** (1 failed)
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 

**Agent final message:** Config loading, aliases and the global parameters are all in place. The existing 25 tests and 20 new ones in `tests/test_config.py` pass, and I ran each scenario by hand under both the venv Python and the system `python3`.

**What's implemented**
- **Config precedence:** runtime flags override the project file, which overrides the global file, which overrides the defaults. The project file is found by searching upward from the current directory, and `appctl.local.yml` is used over `appctl.yml`. The global file comes from `APPCTL_CONFIG_PATH`, or `<APPCTL_ROOT_DIR>/config/config.yml` if that isn't set.
- **Inheritance:** `_: {inherit: ...}` and `_: {merge: true}` work as specified. With `merge`, arrays are appended without removing duplicates.
- **Auto-creation:** missing `locale: en_US` and `installer_version: stable` are added to the global file, keeping what's already there. If the file can't be written, you get an error and exit code 1.
- **Global parameters:** all 13 parameters in the table, with the runtime and file restrictions as listed.
- **Disabled commands:** blocked using the canonical command path, so `site rm` is caught when `site delete` is disabled. Disabling a group such as `cache` also blocks its subcommands.
- **Aliases:** `@name` invocation, `APPCTL_RUNTIME_ALIAS` overrides, `@all` (registered automatically, case-insensitive order), groups with duplicates skipped, and every error message exactly as specified, including the "Did you mean" suggestion. Local a

## checkpoint_3
pass {'Core': 7, 'Functionality': 17, 'Regression': 66, 'Error': 3} / total {'Core': 7, 'Functionality': 23, 'Regression': 71, 'Error': 4}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (3 failed)
- `TestCore::test_config_runtime_overrides_project`: 
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 
- `TestFunctionality::test_strict_args_mode`: 

**checkpoint_3-Error** (1 failed)
- `TestErrors::test_invalid_json_stdin_error`: 

**checkpoint_3-Functionality** (6 failed)
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_file_logging_separator_per_invocation`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 
- `TestFunctionality::test_quiet_does_not_suppress_debug_output`: 
- `TestFunctionality::test_quiet_suppresses_cancellation_warning`: 

**Agent final message:** I've implemented the output, logging and user-interaction spec. All 58 tests pass: the 45 existing ones plus 13 new ones in `tests/test_output.py`. `requirements.txt` is unchanged because nothing new was needed (PyYAML was already listed).

**Changes**
- **Output formats** (`formatter.py`):
  - `json` is indented 4 spaces and `yaml` is block style.
  - Arrays and objects become JSON strings inside `table` and `csv` cells.
  - When there's exactly one result in `table` format, it's shown vertically as `Field`/`Value` rows.
  - `--field` and `--fields` match names case-insensitively and accept a prefix: posts use `post`, users `user`, options `option`, so `--field=title` finds `post_title`. An unknown name gives `Error: Invalid field: <name>.` and exit 1.
- **Messages** (`output.py`):
  - `Error:`, `Warning:`, `Success:` and `Debug:` get their own colors. Color comes from `--color`, `--no-color` or the `color` config key; in auto mode it's on only when STDOUT is a terminal and the OS isn't Windows.
  - Debug lines end with the elapsed time, e.g. `Debug (bootstrap): … (0.003s)`. `--debug=<group>` shows only that group's messages.
  - Errors given as a list of lines are drawn in a box (red when color is on).
- **Log file** (`logfile.py`): written to `<APPCTL_ROOT_DIR>/logs/appctl.log`. Every line starts with a UTC timestamp like `[2026-11-11T05:17:33Z]`, and each run begins with a delimiter line. Success messages are never logged, and `cli completion` runs write nothing at all.
-

## checkpoint_4
pass {'Core': 4, 'Functionality': 19, 'Regression': 93, 'Error': 3} / total {'Core': 5, 'Functionality': 19, 'Regression': 105, 'Error': 4}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (3 failed)
- `TestCore::test_config_runtime_overrides_project`: 
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 
- `TestFunctionality::test_strict_args_mode`: 

**checkpoint_3-Regression** (7 failed)
- `TestErrors::test_invalid_json_stdin_error`: 
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_file_logging_separator_per_invocation`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 
- `TestFunctionality::test_quiet_does_not_suppress_debug_output`: 
- `TestFunctionality::test_quiet_suppresses_cancellation_warning`: 

**checkpoint_4-Core** (1 failed)
- `TestCore::test_detailed_execution_captures_all_fields`: 

**checkpoint_4-Error** (1 failed)
- `TestErrors::test_exit_code_negative_1_warning`: 

**Agent final message:** I've added external command execution, the file cache and archive extraction to the existing `appctl_core` package. All 79 tests pass: the 58 that were already there plus 21 new ones in `tests/test_services.py`. Everything uses only the Python standard library, so `requirements.txt` is unchanged.

**Command execution** (`appctl_core/process.py`)
- `process.run(...)` returns the output, error output, exit code and elapsed time. It logs the command at debug level before running it, then any non-empty output and the return code afterwards.
- `process.run_check(...)` returns only whether the command succeeded.
- Anything in `obfuscate_list` shows as `******` in debug output, but the command still runs with the real value and the result holds the real output. I also mask secrets that appear in the logged output, not just in the command line, so an `echo` of a secret can't leak through debug output.
- An exit code of `-1` prints a non-halting warning about signal handling configuration to STDERR. A child killed by SIGHUP produces this, which is how the tests trigger it.
- `Launcher` re-runs `appctl.py` as a child process with the same global flags, config file path, environment and working directory. Its JSON mode parses the child's output; invalid JSON comes back as `None`.

**File cache** (`appctl_core/file_cache.py`)
- **Location:** `APPCTL_CACHE_DIR`, or `<APPCTL_ROOT_DIR>/.cache/` if that isn't set. The directory is created automatically. If that fails, you get `Warning: Faile

## checkpoint_5
pass {'Core': 2, 'Functionality': 8, 'Regression': 119, 'Error': 2} / total {'Core': 5, 'Functionality': 11, 'Regression': 133, 'Error': 2}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (3 failed)
- `TestCore::test_config_runtime_overrides_project`: 
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 
- `TestFunctionality::test_strict_args_mode`: 

**checkpoint_3-Regression** (7 failed)
- `TestErrors::test_invalid_json_stdin_error`: 
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_file_logging_separator_per_invocation`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 
- `TestFunctionality::test_quiet_does_not_suppress_debug_output`: 
- `TestFunctionality::test_quiet_suppresses_cancellation_warning`: 

**checkpoint_4-Regression** (2 failed)
- `TestCore::test_detailed_execution_captures_all_fields`: 
- `TestErrors::test_exit_code_negative_1_warning`: 

**checkpoint_5-Core** (3 failed)
- `TestCore::test_option_upsert_overwrites`: 
- `TestCore::test_option_write_insert_then_read`: 
- `TestFunctionality::test_all_values_stored_as_strings`: 

**checkpoint_5-Functionality** (3 failed)
- `TestFunctionality::test_empty_string_value_is_not_treated_as_missing`: 
- `TestFunctionality::test_existing_db_opens_without_recreating`: 
- `TestFunctionality::test_parameterized_queries`: 

**Agent final message:** I added a persistent SQLite store in `appctl_core/db.py`. The existing 79 tests and 7 new ones in `tests/test_db.py` all pass. `requirements.txt` is unchanged because `sqlite3` is part of the Python standard library.

**How it works**
- **Location:** the store is `<APPCTL_ROOT_DIR>/db/appctl.sqlite`. The folder, file and tables are created automatically the first time they're needed.
- **When it opens:** every invocation opens the store at startup (`appctl_core/app.py`), so the two errors show up on any command. Command handlers can reach it through `ctx.db`.
- **Errors:** both messages from the spec are written to STDERR as `Error: …` and the tool exits with code 1:
  - If the folder can't be created or the file can't be opened, you get "Unable to initialize connection to appctl sqlite database: <details>".
  - If the file exists but isn't a valid database, or the tables can't be created, you get "Encountered Error while creating table: <details>".

  I tested both on the command line, including a real permissions failure.
- **Settings:** `get_option(key)` returns the stored text, or `False` if the key doesn't exist. `update_option(key, value)` inserts or overwrites. Values are always stored and returned as text, so `"0123"` stays `"0123"` and doesn't become a number.
- **Migration history:** each record holds the migration's name, its category and the time it was applied. `run_migration` skips a migration that was already applied and records it only if it finishes without a

## checkpoint_6
pass {'Core': 0, 'Functionality': 11, 'Regression': 131, 'Error': 1} / total {'Core': 6, 'Functionality': 24, 'Regression': 151, 'Error': 3}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (3 failed)
- `TestCore::test_config_runtime_overrides_project`: 
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 
- `TestFunctionality::test_strict_args_mode`: 

**checkpoint_3-Regression** (7 failed)
- `TestErrors::test_invalid_json_stdin_error`: 
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_file_logging_separator_per_invocation`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 
- `TestFunctionality::test_quiet_does_not_suppress_debug_output`: 
- `TestFunctionality::test_quiet_suppresses_cancellation_warning`: 

**checkpoint_4-Regression** (2 failed)
- `TestCore::test_detailed_execution_captures_all_fields`: 
- `TestErrors::test_exit_code_negative_1_warning`: 

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

**Agent final message:** I've added container, compose, volume and network support to `appctl`. All 100 tests pass: the 86 that were already there plus 14 new ones. The new tests use a fake `docker` script on PATH, because this machine has the Docker client but no running daemon. I also ran the commands against the real client, but nothing has been run against a live daemon yet. `requirements.txt` is unchanged, since PyYAML was already listed.

**What's new**
- **`appctl_core/containers.py`** (the core logic):
  - **Compose merging:** the base file comes first. If `custom-compose` is set, only that file is applied after it. Otherwise the tool looks for overrides in a fixed order: the standard `*.override.yml` files, then `docker-compose-custom.yml`, then `user-docker-compose/*.yml` sorted by name. Files that aren't `.yml`/`.yaml` are ignored. A missing custom file prints the exact warning and is skipped.
  - **Containers:** status is `running`, `exited` or missing. Booting starts an exited container, does nothing if it's already running, and creates it if it's missing. Start, stop and restart work by name. If Docker isn't installed, the exact error is printed and the command exits.
  - **Compose actions:** `up -d` can be limited to a list of services, and `down` also removes the project's volumes. `exec` adds `-T` when `skip-tty` is truthy and accepts a user, a shell and a shell-wrapper mode.
  - **Volumes:** creation skips `skip_volume: true` and volumes that already exist, adds labels naming the to

## checkpoint_7
pass {'Core': 1, 'Functionality': 10, 'Regression': 143, 'Error': 2} / total {'Core': 5, 'Functionality': 21, 'Regression': 184, 'Error': 4}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (3 failed)
- `TestCore::test_config_runtime_overrides_project`: 
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 
- `TestFunctionality::test_strict_args_mode`: 

**checkpoint_3-Regression** (7 failed)
- `TestErrors::test_invalid_json_stdin_error`: 
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_file_logging_separator_per_invocation`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 
- `TestFunctionality::test_quiet_does_not_suppress_debug_output`: 
- `TestFunctionality::test_quiet_suppresses_cancellation_warning`: 

**checkpoint_4-Regression** (2 failed)
- `TestCore::test_detailed_execution_captures_all_fields`: 
- `TestErrors::test_exit_code_negative_1_warning`: 

**checkpoint_5-Regression** (6 failed)
- `TestCore::test_option_upsert_overwrites`: 
- `TestCore::test_option_write_insert_then_read`: 
- `TestFunctionality::test_all_values_stored_as_strings`: 
- `TestFunctionality::test_empty_string_value_is_not_treated_as_missing`: 
- `TestFunctionality::test_existing_db_opens_without_recreating`: 
- `TestFunctionality::test_parameterized_queries`: 

**checkpoint_6-Regression** (21 failed)
- `TestCore::test_compose_merge_base_always_first`: 
- `TestCore::test_container_status_exited`: 
- `TestCore::test_container_status_false_not_exists`: 
- `TestCore::test_container_status_running`: 
- `TestCore::test_project_naming_prefix`: 
- `TestCore::test_volume_creation_with_labels`: 
- `TestErrors::test_container_runtime_not_installed_error`: 
- `TestErrors::test_network_connect_failure_raises`: 
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

**checkpoint_7-Core** (4 failed)
- `TestCore::test_disk_space_check_blocks_upgrade`: 
- `TestCore::test_migration_discovery_and_ascending_sort`: 
- `TestCore::test_migration_execution_creates_record`: 
- `TestCore::test_migration_failure_triggers_batch_rollback`: 

**checkpoint_7-Error** (2 failed)
- `TestErrors::test_image_pull_failure_error`: 
- `TestErrors::test_migration_rollback_deletes_records`: 

**checkpoint_7-Functionality** (11 failed)
- `TestFunctionality::test_container_migration_failure_blocks_image_pulls`: 
- `TestFunctionality::test_container_migrations_after_db_migrations`: 
- `TestFunctionality::test_disk_space_exact_threshold_allows_upgrade`: 
- `TestFunctionality::test_disk_space_failure_blocks_upgrade_mutations`: 
- `TestFunctionality::test_image_pulls_sequential`: 
- `TestFunctionality::test_no_pending_migrations_do_not_duplicate_history`: 
- `TestFunctionality::test_post_upgrade_saves_versions`: 
- `TestFunctionality::test_rollback_no_undo_skipped`: 
- `TestFunctionality::test_rollback_strict_reverse_order`: 
- `TestFunctionality::test_rollback_undo_failure_logged_continues`: 
- `TestFunctionality::test_runtime_disk_space_failure_blocks_upgrade_mutations`: 

**Agent final message:** The upgrade system is in place. All 138 tests pass: the original 100, which I didn't change, plus 38 new ones in `tests/test_upgrade.py` that drive a fake `docker` script. `requirements.txt` is unchanged because I added no dependencies.

**How it runs**
- **Automatically:** before a command runs, if the stored `version` differs from the tool's `VERSION`.
- **Manually:** with `appctl cli migrate`.
- **Fresh installs:** if no version has ever been stored, nothing runs on its own. This keeps commands like `cli version` working on a new install with no Docker or disk-space checks.

**Order of steps** (`appctl_core/upgrade.py`)
1. **Disk check:** at least 5 GiB free under both the tool root and Docker's data root, before anything changes. If either is short, there is a single `Error: Minimum 5GB disk space is required…` and exit 1.
2. Database migrations, then container migrations.
3. Compose tool check. If it's below 2.20.2 (compared as semantic versions), a new copy is downloaded, tested, and installed in `~/.docker/cli-plugins`. The old one is kept as a backup and put back if anything fails.
4. Changed images are pulled one at a time.
5. Global services in `<root>/services` are replaced, but only those whose image changed (`--no-deps`).
6. Each project in the database that uses a changed image has its containers stopped, removed and restarted, with the image tags updated in its compose files.
7. Image versions and the tool version are saved.
8. Old images and networks are prune

## checkpoint_8
pass {'Core': 5, 'Functionality': 20, 'Regression': 137, 'Error': 2} / total {'Core': 7, 'Functionality': 31, 'Regression': 214, 'Error': 3}

**checkpoint_1-Regression** (10 failed)
- `TestCore::test_help_rewrite`: 
- `TestCore::test_help_rewrite_for_multi_level_command`: 
- `TestErrors::test_excess_positional_args_error`: 
- `TestErrors::test_missing_required_positional_shows_usage`: 
- `TestErrors::test_multiple_parameter_errors_collected`: 
- `TestErrors::test_unknown_associative_no_suggestion`: 
- `TestErrors::test_unknown_associative_with_suggestion`: 
- `TestFunctionality::test_parent_command_no_handler_shows_subcommands`: 
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (5 failed)
- `TestCore::test_config_runtime_overrides_project`: 
- `TestFunctionality::test_project_config_local_yml_priority_overrides_project_disabled_command`: 
- `TestFunctionality::test_project_config_search_stops_at_first_matching_directory`: 
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 
- `TestFunctionality::test_strict_args_mode`: 

**checkpoint_3-Regression** (21 failed)
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
- `TestFunctionality::test_file_logging_separator_per_invocation`: 
- `TestFunctionality::test_formats_preserve_same_underlying_values`: 
- `TestFunctionality::test_ids_format_space_separated`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 
- `TestFunctionality::test_quiet_does_not_suppress_debug_output`: 
- `TestFunctionality::test_yaml_format_output`: 

**checkpoint_4-Regression** (2 failed)
- `TestCore::test_detailed_execution_captures_all_fields`: 
- `TestErrors::test_exit_code_negative_1_warning`: 

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

**checkpoint_7-Regression** (16 failed)
- `TestCore::test_disk_space_check_blocks_upgrade`: 
- `TestCore::test_migration_discovery_and_ascending_sort`: 
- `TestCore::test_migration_execution_creates_record`: 
- `TestCore::test_migration_failure_triggers_batch_rollback`: 
- `TestErrors::test_image_pull_failure_error`: 
- `TestErrors::test_migration_rollback_deletes_records`: 
- `TestFunctionality::test_container_migration_failure_blocks_image_pulls`: 
- `TestFunctionality::test_container_migrations_after_db_migrations`: 
- `TestFunctionality::test_disk_space_exact_threshold_allows_upgrade`: 
- `TestFunctionality::test_disk_space_failure_blocks_upgrade_mutations`: 
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

**checkpoint_8-Functionality** (11 failed)
- `TestFunctionality::test_cli_check_update_filtered_no_updates_mentions_filter`: 
- `TestFunctionality::test_cli_check_update_last_filter_wins`: 
- `TestFunctionality::test_cli_check_update_no_updates_success`: 
- `TestFunctionality::test_cli_check_update_table_format_no_updates_success`: 
- `TestFunctionality::test_cli_cmd_dump_alphabetical`: 
- `TestFunctionality::test_cli_info_list_format_field_order`: 
- `TestFunctionality::test_cli_param_dump_var_export_output`: 
- `TestFunctionality::test_cli_param_dump_with_values_reflects_runtime_config`: 
- `TestFunctionality::test_cli_update_requires_confirmation`: 
- `TestFunctionality::test_older_binary_cli_warning`: 
- `TestFunctionality::test_runtime_binary_resolution_precedence`: 

**Agent final message:** Everything in the spec is implemented on top of the existing `appctl` code, and the full test suite passes (217 tests, including 76 new ones in `tests/test_cli.py`). No new dependencies were needed, so `requirements.txt` is unchanged.

**What was added**
- **System checks** (`system.py`): every command except the `cli`, `config` and `help` families now checks that:
  - the container runtime answers `docker ps`, retrying after 0.2s, 0.4s and 0.8s before giving up;
  - the compose tool is installed (the standalone `docker-compose` binary first, then the `docker compose` plugin) and is at least version 2.0.0;
  - Python is at least 3.8.

  On macOS the runtime error includes a Homebrew install hint. Any failure exits with code 1.
- **Startup** (`startup.py`):
  - **First run:** runs pending migrations, stores the version and prints `Success: AppCtl has been set up successfully.` On macOS it also prints Docker Desktop setup steps.
  - **Version comparison:** a newer binary migrates. An older one warns for `cli` commands and stops everything else with exit 1. Nightly builds always migrate.
  - **Auto-update:** only in a terminal with a writable binary. The first check just records the time; later checks run after the configured number of days, and if an update is found it starts the update.
- **Releases and self-update** (`releases.py`):
  - **`check-update`:** compares versions semantically and supports the filters (last one wins) and all five output formats.
  - **Nightly builds
