# Failure summary: runs/recli/c2_modular_s1_20261110T2205

## checkpoint_1
pass {'Core': 11, 'Functionality': 15, 'Regression': 0, 'Error': 6} / total {'Core': 11, 'Functionality': 17, 'Regression': 0, 'Error': 6}

**checkpoint_1-Functionality** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**Agent final message:** I've built `appctl.py` and its supporting package, and all 45 tests pass (unit tests plus end-to-end runs of the real script). It uses only the Python standard library, so `requirements.txt` holds just a comment saying that. A virtual environment is set up in `.venv`.

**What it does (each behaviour was run and checked):**
- **No arguments / `appctl help`:** prints the top-level commands in case-insensitive alphabetical order, as aligned name/description columns, and exits 0.
- **Command lookup:** commands are matched one level at a time (`site create`, `user meta get`). A command with subcommands but no handler, like `appctl site`, prints a `usage:` / `   or:` block listing its subcommands. Aliases are checked before any synonym suggestion, so `user remove 2` runs `user delete`.
- **Rewrites:** `<cmd> --help` becomes `help <cmd>`. `--version` becomes `cli version`, but only when no command is given, so `plugin install x --version=1.2` is left alone.
- **Unknown commands:** the error messages match the spec exactly and go to stderr with exit code 1, plus `Did you mean '…'?` when there is a close match.
- **Suggestions:** they come either from a fixed synonym list (`new`/`add` → `create`, `remove` → `delete`, …), used only when the target command exists, or from edit distance. Ties are broken alphabetically, so the same input always gives the same suggestion.
- **Argument checks:**
  - A missing required positional prints the usage line to stdout (exit 1).
  - Extra positional

## checkpoint_2
pass {'Core': 9, 'Functionality': 22, 'Regression': 32, 'Error': 3} / total {'Core': 9, 'Functionality': 23, 'Regression': 34, 'Error': 5}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Functionality** (1 failed)
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 

**checkpoint_2-Error** (2 failed)
- `TestErrors::test_all_no_aliases_error`: 
- `TestErrors::test_unknown_alias_error`: 

**Agent final message:** I've implemented config loading, aliases and the global parameters in the existing `appctl_cli` code. The 45 existing tests and 19 new ones in `tests/test_config.py` all pass. I also ran the spec's example scenarios by hand, using a stand-in `ssh` script because this machine has no `ssh`, and the error messages and exit codes match the spec.

**What's in place**
- **Config loading** (`appctl_cli/config_loader.py`): runtime flags override the project file, which overrides the global file, which overrides defaults. The project file is found by searching upward, with `appctl.local.yml` beating `appctl.yml`. `_: {inherit, merge}` works, and missing `locale` / `installer_version` keys are added to the global config. If that file can't be written, the tool prints an `Error:` and exits 1.
- **Global parameters** (`runtime_config.py`): the 13 from the table, with the runtime and file rules applied. So `--locale` is still passed to `config create` as a command option, and `debug`/`quiet` in a file are ignored. Deprecated parameters print the spec's warning when used as flags, and hidden ones are left out of `cli param-dump`.
- **Disabled commands**: disabling a parent such as `db` also blocks `db query`, and the error names the entry that matched.
- **Aliases** (`app.py`): single aliases, groups (deduplicated, in order of first appearance), `@all`, runtime aliases from `APPCTL_RUNTIME_ALIAS`, local `path` resolved against the config file's folder, and the unknown-alias suggestion.
- *

## checkpoint_3
pass {'Core': 7, 'Functionality': 19, 'Regression': 66, 'Error': 3} / total {'Core': 7, 'Functionality': 23, 'Regression': 71, 'Error': 4}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (3 failed)
- `TestErrors::test_all_no_aliases_error`: 
- `TestErrors::test_unknown_alias_error`: 
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 

**checkpoint_3-Error** (1 failed)
- `TestErrors::test_confirmation_prompt_non_y_aborts`: 

**checkpoint_3-Functionality** (4 failed)
- `TestFunctionality::test_confirmation_accepts_trimmed_uppercase_y`: 
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 

**Agent final message:** I implemented the whole spec on top of the existing `appctl_cli` package. All 92 tests pass: the 64 that were already there plus 28 new ones in `tests/test_output.py`. `requirements.txt` is unchanged because PyYAML was already listed and nothing new was needed.

**What changed**
- **Output formats** (`formatter.py`): JSON is now pretty-printed with 4-space indentation and keeps column order. YAML is real block style via PyYAML. Arrays and objects appear as JSON strings in `table` and `csv` output. A table with exactly one result switches to a vertical Field/Value layout.
- **Field selection**: `--field` and `--fields` match names case-insensitively and accept a per-command prefix, so `post get 1 --field=title` finds `post_title`. I set prefixes for posts (`post`), users (`user`) and options (`option`). Unknown names give `Error: Invalid field: <name>.` and exit 1.
- **Messages and color** (`output.py`): `Error:`, `Warning:`, `Success:` and `Debug:` each get their own color. Color follows `--color`, `--no-color` and the `color` config key; in auto mode it's on only when STDOUT is a terminal and the OS isn't Windows.
- **Debug**: each line ends with elapsed seconds, e.g. `(0.003s)`. `--debug=<group>` shows only that group, labelled `Debug (<group>):`. I added `bootstrap` messages that report which config files were loaded.
- **Multi-line errors**: there is a new boxed error output, but no command currently uses it. Existing multi-line errors such as "Did you mean…" and "Paramet

## checkpoint_4
pass {'Core': 4, 'Functionality': 19, 'Regression': 95, 'Error': 3} / total {'Core': 5, 'Functionality': 19, 'Regression': 105, 'Error': 4}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (3 failed)
- `TestErrors::test_all_no_aliases_error`: 
- `TestErrors::test_unknown_alias_error`: 
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 

**checkpoint_3-Regression** (5 failed)
- `TestErrors::test_confirmation_prompt_non_y_aborts`: 
- `TestFunctionality::test_confirmation_accepts_trimmed_uppercase_y`: 
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 

**checkpoint_4-Core** (1 failed)
- `TestCore::test_detailed_execution_captures_all_fields`: 

**checkpoint_4-Error** (1 failed)
- `TestErrors::test_exit_code_negative_1_warning`: 

**Agent final message:** I've added external command execution, the file cache and archive extraction to the existing `appctl` codebase. All 107 tests pass: the 92 that were already there and 15 new ones in `tests/test_process_cache_extract.py`. `requirements.txt` is unchanged because everything uses the Python standard library.

**Command execution** (`appctl_cli/process.py`)
- **Detailed run:** `run_command()` returns the output, error output, exit code and elapsed time. With `--debug` it logs `COMMAND: …` before running, then any non-empty `STDOUT:` / `STDERR:`, then `RETURN CODE: …`.
- **Success-only run:** `exec_command()` returns true or false and logs the same way.
- **Hiding secrets:** pass an obfuscation list and those strings show as `******` in every debug line. The command itself still runs with the real values, and the returned result has the real output.
- **Exit code -1:** this produces a warning on STDERR about signal handling configuration and does not stop the tool. The existing SSH/Docker runner gives the same warning.
- **Running itself as a child:** `launch_self()` / `runcommand()` pass on the config file path and any global flags that differ from the defaults. A JSON mode parses the child's output as JSON before returning it.

**File cache** (`appctl_cli/file_cache.py`)
- **Location:** the cache uses `APPCTL_CACHE_DIR`, or `<APPCTL_ROOT_DIR>/.cache/` if that isn't set, and creates the directory if needed. If it can't be created, it prints `Warning: Failed to create directory '<p

## checkpoint_5
pass {'Core': 2, 'Functionality': 8, 'Regression': 121, 'Error': 2} / total {'Core': 5, 'Functionality': 11, 'Regression': 133, 'Error': 2}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (3 failed)
- `TestErrors::test_all_no_aliases_error`: 
- `TestErrors::test_unknown_alias_error`: 
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 

**checkpoint_3-Regression** (5 failed)
- `TestErrors::test_confirmation_prompt_non_y_aborts`: 
- `TestFunctionality::test_confirmation_accepts_trimmed_uppercase_y`: 
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 

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

**Agent final message:** The persistent store is in place. All 107 existing tests still pass, and I tried each requirement by hand: by running the CLI for the error cases and by calling the store's functions from a Python script for the rest. I didn't add tests to the repo.

**What I added**
- **`appctl_cli/database.py`**: a SQLite database at `<APPCTL_ROOT_DIR>/db/appctl.sqlite`. It has two tables:
  - `options`: `key` (the primary key), `value` and `modified_on`.
  - `migrations`: `migration`, `type` and `timestamp`, with each name/type pair stored once.
- **`appctl_cli/app.py`**: every run now opens the database (creating it if needed) before loading config, and closes it at the end.

**How it behaves**
- **Settings:** `get_option` returns the stored string, or `False` if the key is missing (no error). `set_option` adds a key or overwrites it, and always stores the value as a string (`5` comes back as `"5"`).
- **Migration history:**
  - `apply_migration` skips migrations already recorded, and only records one after it succeeds.
  - `rollback_migration` removes the record.
  - `run_migrations` runs the pending ones in name order. If one fails, it runs that migration's undo step, leaves no record for it, and passes the error on.
- **Safe values:** all queries use bound parameters. A value like `a'; DROP TABLE options;--` is stored and read back unchanged.
- **Times:** `modified_on` and `timestamp` are UTC in the form `2026-11-11T03:47:54Z`. Lists come back sorted (options by key, migrations by name

## checkpoint_6
pass {'Core': 0, 'Functionality': 11, 'Regression': 133, 'Error': 2} / total {'Core': 6, 'Functionality': 24, 'Regression': 151, 'Error': 3}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (3 failed)
- `TestErrors::test_all_no_aliases_error`: 
- `TestErrors::test_unknown_alias_error`: 
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 

**checkpoint_3-Regression** (5 failed)
- `TestErrors::test_confirmation_prompt_non_y_aborts`: 
- `TestFunctionality::test_confirmation_accepts_trimmed_uppercase_y`: 
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 

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

**checkpoint_6-Error** (1 failed)
- `TestErrors::test_container_runtime_not_installed_error`: 

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

**Agent final message:** I've implemented the spec as a new module, `appctl_cli/container.py`, plus a new `site config` command. The full test suite passes: 125 tests, including a new `tests/test_container.py`. No Docker daemon is running here, so nothing was run against a real Docker. The new tests use a fake `docker` script that records the commands it receives.

**`python appctl.py site config --services`**
- It lists services in the order they appear in the files: base services first, then any new ones from overrides. It reads the YAML itself rather than calling `docker compose config --services`, because Docker's command reordered `zeta, alpha, mid` to `alpha, zeta, mid` when I tried it. As a side effect it works without Docker.
- It looks for the compose file in the current directory and its parent directories. You can point it elsewhere with `--path`, or name a site, which it looks up under `projects_path`.
- Without `--services`, it prints the whole merged configuration as YAML.
- If no compose file is found, it exits with an error.

**Compose file merging**
- The base file is the first of `docker-compose.yml`, `docker-compose.yaml`, `compose.yml` or `compose.yaml` that exists. Later files override earlier ones.
- If `custom-compose` is set, that file is applied last. If it doesn't exist, the tool prints the exact warning from the spec and uses only the base file.
- Otherwise it picks up `docker-compose.override.yml` (and the `compose.override` variants), then every `.yml`/`.yaml` file in `us

## checkpoint_7
pass {'Core': 1, 'Functionality': 10, 'Regression': 146, 'Error': 2} / total {'Core': 5, 'Functionality': 21, 'Regression': 184, 'Error': 4}

**checkpoint_1-Regression** (2 failed)
- `TestFunctionality::test_required_associative_empty_value_is_rejected`: 
- `TestFunctionality::test_required_associative_missing_error`: 

**checkpoint_2-Regression** (3 failed)
- `TestErrors::test_all_no_aliases_error`: 
- `TestErrors::test_unknown_alias_error`: 
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 

**checkpoint_3-Regression** (5 failed)
- `TestErrors::test_confirmation_prompt_non_y_aborts`: 
- `TestFunctionality::test_confirmation_accepts_trimmed_uppercase_y`: 
- `TestFunctionality::test_confirmation_blank_response_cancels`: 
- `TestFunctionality::test_csv_serializes_complex_values_as_json_strings`: 
- `TestFunctionality::test_json_stdin_supplies_missing_positional_argument`: 

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

**checkpoint_6-Regression** (20 failed)
- `TestCore::test_compose_merge_base_always_first`: 
- `TestCore::test_container_status_exited`: 
- `TestCore::test_container_status_false_not_exists`: 
- `TestCore::test_container_status_running`: 
- `TestCore::test_project_naming_prefix`: 
- `TestCore::test_volume_creation_with_labels`: 
- `TestErrors::test_container_runtime_not_installed_error`: 
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

**Agent final message:** I've implemented the full upgrade flow from the spec. All 146 tests pass: the 125 that were already there plus 21 new ones in `tests/test_upgrade.py`, which use a fake `docker` binary. No new dependencies were needed, so `requirements.txt` is unchanged.

**How it runs**
- **When:** automatically before any command if the stored tool version differs from the running one, or explicitly with the new `appctl cli migrate`. On a fresh install with no stored version nothing runs automatically; this keeps every existing command from trying to upgrade in a new environment.
- **Order:** disk-space check first, then database migrations, container migrations, image pulls, compose tool upgrade, global containers, per-project containers, and finally saving the new versions. If any step fails, every completed step is undone in reverse. Pruning old images and networks happens last and only produces warnings if it fails.
- **Rollback rules:** an undo that fails is logged and the rollback continues; steps with no undo are skipped. A failed step's own undo also runs, so it can clean up partial work. The one exception is a failed migration: only the migrations that completed before it are rolled back, as the spec says.

**Migrations**
- Files live in `<source>/migrations/{db,container}/<number>_<name>.py`. The source is either the tool itself (`appctl_cli/migrations/`) or an extension under the packages directory.
- They're recorded in the `migrations` table as `<source>:<file name>` with their 

## checkpoint_8
pass {'Core': 5, 'Functionality': 21, 'Regression': 139, 'Error': 2} / total {'Core': 7, 'Functionality': 31, 'Regression': 214, 'Error': 3}

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
- `TestErrors::test_all_no_aliases_error`: 
- `TestErrors::test_unknown_alias_error`: 
- `TestFunctionality::test_project_config_local_yml_priority_overrides_project_disabled_command`: 
- `TestFunctionality::test_project_config_search_stops_at_first_matching_directory`: 
- `TestFunctionality::test_ssh_pre_cmd_injected_before_remote_command`: 

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

**checkpoint_8-Functionality** (10 failed)
- `TestFunctionality::test_cli_check_update_filtered_no_updates_mentions_filter`: 
- `TestFunctionality::test_cli_check_update_last_filter_wins`: 
- `TestFunctionality::test_cli_check_update_no_updates_success`: 
- `TestFunctionality::test_cli_check_update_table_format_no_updates_success`: 
- `TestFunctionality::test_cli_cmd_dump_alphabetical`: 
- `TestFunctionality::test_cli_info_list_format_field_order`: 
- `TestFunctionality::test_cli_info_packages_path_null_when_missing`: 
- `TestFunctionality::test_cli_param_dump_with_values_reflects_runtime_config`: 
- `TestFunctionality::test_cli_update_requires_confirmation`: 
- `TestFunctionality::test_older_binary_cli_warning`: 

**Agent final message:** I've implemented the full spec on top of the existing `appctl` codebase. The full suite passes: 208 tests, 62 of them new in `tests/test_self_management.py`. No new dependencies, so `requirements.txt` is unchanged (stdlib plus the existing PyYAML).

**New modules**
- **`system.py`** – the system checks:
  - The Docker probe (`docker ps -q`) tries 3 times, waiting 0.5s then 1s between attempts.
  - The compose tool must exist and be at least 2.27.0, compared as semantic versions.
  - The Python runtime must be at least 3.8.
  - Every failing check is reported on STDERR, and the macOS error includes a `brew install --cask docker` hint.
  - Also here: runtime binary lookup (`APPCTL_RUNTIME_BIN`, then `APPCTL_RUNTIME_BIN_USED`, then the running interpreter, then `python3`) and archive-mode detection.
- **`startup.py`** – first run (create the store, run pending migrations, print the success message, plus Docker Desktop instructions on macOS) and the version comparison on every invocation (newer migrates, older warns for `cli` and errors otherwise, nightly always migrates).
- **`self_update.py`** – release lookup, `check-update`, `update` (download, optional checksum, then a test run of the new binary against a throwaway root before an atomic replace), and the periodic auto-update check.
- **`build_archive.py`** – builds the distributable `appctl.pyz` (a Python zip app), which is what "archive mode" means here.

**Decisions you may want to revisit**
- **`cli version` now prints on
