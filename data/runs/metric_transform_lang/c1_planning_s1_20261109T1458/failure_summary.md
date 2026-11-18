# Failure summary: runs/metric_transform_lang/c1_planning_s1_20261109T1458

## checkpoint_1
pass {'Core': 4, 'Functionality': 25, 'Regression': 0, 'Error': 17} / total {'Core': 4, 'Functionality': 25, 'Regression': 0, 'Error': 17}

**Agent final message:** I've written `mtl.py`, along with `DESIGN.md` and a `requirements.txt` whose only entry is `tzdata`. It runs in the virtual environment at `.venv`. I tested it by hand from the command line; there is no automated test suite.

**What I checked:** I ran about 40 cases, and each produced the output or exit code I expected:
- the four output shapes: plain aggregate, `group_by`, `window`, and both together;
- row ordering and key ordering;
- `count(*)` returning `0` and other aggregates returning `null` when no rows match;
- `round` rounding half away from zero (`2.675 → 2.68`, `-2.5 → -3`);
- `--tz` and `--timestamp-format`;
- a `#` inside a quoted string not being treated as a comment;
- every error type, each printing one `ERROR:<TYPE>:<Message>` line with the right exit code.

**Choices where the spec is ambiguous.** Some of these may not match what your hidden tests expect:
- **Arithmetic is supported.** The spec mentions "numeric ops" and "division by zero in user expression", so `apply` and `filter` accept `+ - * / %`. Dividing by zero, or any result that isn't a finite number, exits with code 4.
- **Empty windows are left out.** Only time windows that contain events appear in the output; gaps between them don't produce rows with `count: 0`.
- **Which errors get which codes:**
  - An unknown column, or `sum(*)`, is a type error (exit 2).
  - An unknown function, the wrong number of arguments, a bad duration, a duplicate alias, or an alias that clashes with an output key is 

## checkpoint_2
pass {'Core': 3, 'Functionality': 37, 'Regression': 46, 'Error': 12} / total {'Core': 3, 'Functionality': 37, 'Regression': 46, 'Error': 12}

**Agent final message:** I've extended `mtl.py` to handle the full Part 2 spec, and Part 1 still works. A Part 1 pipeline gives byte-identical output to before, from a file and from stdin. I ran about 35 hand-written cases, covering the spec's example and each error rule, and all gave the expected output and exit code. I had no official test suite, so that's the only testing. No new dependencies, so `requirements.txt` is unchanged.

**What's supported:**
- **Schemas:** a child schema inherits from its base and can override field types. Same type or `int`→`float` is allowed; any other change exits 2. Circular inheritance, unknown base schemas and multiple inheritance (`extends A, B`) exit 1. A calculated field that refers to an unknown, later-declared or self field exits 1.
- **CSV columns:** a file with schema blocks loads only the physical fields of the schema used by the pipeline, with their declared types. A missing column exits 3, and extra CSV columns are ignored.
- **Params:** missing with no default exits 1; a `--param` value that won't parse as its declared type exits 2; last value wins. Both `--param a=1 --param b=2` and `--param a=1 b=2` work.
- **`calc` statements:** `pre` calcs are computed per row before anything else; `post_agg` calcs run after the final sort, in the order declared, and can use group/window keys, aggregate aliases and earlier post-agg calcs. Mismatched declared types and post-agg references to per-row fields (e.g. `day(timestamp)`) exit 2. Name collisions and aggregate 

## checkpoint_3
pass {'Core': 3, 'Functionality': 51, 'Regression': 98, 'Error': 11} / total {'Core': 3, 'Functionality': 52, 'Regression': 98, 'Error': 11}

**checkpoint_3-Functionality** (1 failed)
- `test_checkpoint_3_hidden[04_many_files]`: E           AssertionError

**Agent final message:** I've extended `mtl.py` to cover the spec: multiple inputs, CSV/TSV (optionally gzipped) and Parquet, null markers, bad-record logging, and results that don't depend on input order. I tested it by hand with ad-hoc data and scripts; there is no automated test suite. In that testing, a mixed CSV + gzipped TSV + Parquet run gave the expected totals. Splitting 3,000 shuffled rows across the three formats gave byte-identical output on three runs. Strict mode, bad inputs and the bad-records file all behaved as described below.

`pyarrow` is now installed in the existing `.venv` and listed in `requirements.txt`. Pandas is not needed.

**Inputs**
- `--input` can be repeated and takes several paths at once, so an unquoted shell glob still works. Each path can be a file, a directory (with `--recursive` to go into subfolders) or a glob.
- Files matched by more than one input are read only once. Files are always processed in sorted path order.
- **Format:** chosen by file extension, case-insensitive. A file whose extension doesn't identify its format uses `--format`; if that is `auto`, it fails with exit 3. `.gz` files are decompressed.
- A missing path, a glob that matches nothing overall, an empty file, a corrupt gzip or Parquet file, or invalid UTF-8 all exit with 3.
- `--csv` still works as another name for `--input`.

**Null semantics**
- Comparisons, `!`, `in` and `starts_with`/`ends_with`/`contains` now return null when an input is null. `&` and `|` use three-valued logic, so `fals

## checkpoint_4
pass {'Core': 1, 'Functionality': 55, 'Regression': 117, 'Error': 4} / total {'Core': 1, 'Functionality': 57, 'Regression': 164, 'Error': 4}

**checkpoint_3-Regression** (1 failed)
- `test_checkpoint_3_hidden[04_many_files]`: E           AssertionError

**checkpoint_4-Functionality** (2 failed)
- `test_checkpoint_4_hidden[05_join_full_outer]`: E           AssertionError
- `test_checkpoint_4_regression[33_recursive_directory]`: E           AssertionError

**Agent final message:** I've extended `mtl.py` with `--ingest-config` and everything in the spec: named sources, per-source mapping and schema checks, `sources {}` / `with` / `join` syntax, and the new config-error exit code 5. I tested it with hand-built fixtures and checked the results by hand; the workspace has no test suite, so nothing beyond that has been run.

**What I ran:**
- **Spec example:** Parquet web feed plus gzipped POS CSV, `within 10m`, 1h window. The output matches a hand calculation.
- **Joins:** all four join types (`full` gives the right `count(col)` nulls), chained joins via `as WP` and via `_`, and per-source `with` filters and calcs.
- **Mapping:** drop → rename → cast → defaults, required fields, per-source time zones, `--bad-records-out` and `--strict`.
- **Errors:** every listed case returns the right code and a single `ERROR:<TYPE>:<msg>` line — for example duplicate project names (1), a string/number `on` comparison (2), a missing config file (3), and tied precedence or an unknown schema (5).
- **Old behaviour:** for runs without a config, the old and new versions give identical output. The two intentional differences: `W.price` is now valid syntax (a non-existent `W.price` is an unknown-column error, exit 2, instead of a syntax error, exit 1), and the missing-`--input` message now also mentions `--ingest-config` (still exit 3).

**Dependency:** I added `PyYAML>=6.0` to `requirements.txt` and installed it in `.venv`. There's also a small built-in YAML reader as a fallbac

## checkpoint_5
pass {'Core': 1, 'Functionality': 19, 'Regression': 46, 'Error': 5} / total {'Core': 1, 'Functionality': 20, 'Regression': 48, 'Error': 5}

**checkpoint_5-Functionality** (1 failed)
- `test_checkpoint_5_hidden[03_join_full_outer]`: E           AssertionError

**checkpoint_5-Regression** (2 failed)
- `test_checkpoint_5_regression[11_null_aggregates]`: E       AssertionError
- `test_checkpoint_5_regression[33_recursive_directory]`: E           AssertionError

**Agent final message:** I've extended `mtl.py` with all three Part 5 features: version gating, deterministic resume, and the metadata file. I also added `xxhash` to `requirements.txt` and installed it in the venv. I tested it against fixture data in every input mode (ingest-config union, joins, `--input` with a block DSL, and the legacy line DSL), using CSV, gzip and Parquet files. I also compared it against a backup of the Part 4 code with the header line removed: outputs, bad-records files and error messages are identical. The only difference is the new warning line for older versions.

**What the tests showed**
- **No-change resume:** output is byte-identical to the fresh run, and metadata is identical between resumes apart from `run_id` and the timestamps. The fresh-run metadata also differs in `"resume": false`.
- **Files really are skipped:** I edited a file's content but kept its size and modified time. With the default `mtime_size` fingerprint the resume used the saved data and the output didn't change. With `xxhash64` the edit was caught and the file was reprocessed.
- **Incremental runs:** after adding a new file and appending to an existing one, the resumed output matched a from-scratch run in all four modes.
- **Errors:**
  - Exit 6: missing header, `mtl_version 2.0`, `--resume` without `--state-dir`, missing or malformed state file, DSL or config hash mismatch, and `--state-dir` pointing at a file.
  - Exit 1: a malformed header, and features above the declared version (blocks under 1.1
