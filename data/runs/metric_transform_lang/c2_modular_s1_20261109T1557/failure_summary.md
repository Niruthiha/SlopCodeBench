# Failure summary: runs/metric_transform_lang/c2_modular_s1_20261109T1557

## checkpoint_1
pass {'Core': 4, 'Functionality': 25, 'Regression': 0, 'Error': 17} / total {'Core': 4, 'Functionality': 25, 'Regression': 0, 'Error': 17}

**Agent final message:** I've built the `mtl.py` CLI with the design plan in `DESIGN.md`. I ran it by hand against sample CSVs and DSL files covering each feature and every exit code (0–4), and all gave the expected output. There is no automated test suite.

**Layout:** `mtl.py` is a thin entry point, and the logic is in the `mtl_engine/` package, one module per stage (CSV loading, DSL parsing, type checking, evaluation, aggregation, JSON output). `DESIGN.md` has the module table. A virtual environment is in `.venv`. `requirements.txt` lists only `tzdata`, so timezones still work on systems without a zoneinfo database.

**What the manual runs confirmed:**
- **Output shape:** all four layouts (no grouping, `group_by` only, `window` only, both) come out with the required row order and key order.
- **Timezones:** naive timestamps pick up `--tz` (checked with New York and Tokyo), and `--timestamp-format` works.
- **Statements and expressions:** aggregate lists can span several lines, including with a leading comma.
- **Rounding:** `round` goes half away from zero (2.5 → 3.0, −2.5 → −3.0, 2.675 to two places → 2.68).
- **Empty input:** with no matching rows, `count(*)` is 0 and the other aggregates are `null`. A CSV with only a header gives `[]` when grouped.
- **Errors:** each case prints one `ERROR:<TYPE>:<msg>` line and exits with the right code, including division by zero and a sum that overflows (both exit 4).

**Where the spec was unclear, I chose:**
- **Arithmetic:** the spec mentions "numeric ops"

## checkpoint_2
pass {'Core': 3, 'Functionality': 37, 'Regression': 46, 'Error': 12} / total {'Core': 3, 'Functionality': 37, 'Regression': 46, 'Error': 12}

**Agent final message:** I've extended the CLI to handle the Part 2 DSL. Both examples in the spec run, and the HourlyKPIs output has the keys in exactly the order the spec gives. `requirements.txt` is unchanged because no new dependencies were needed.

**Testing:**
- **Error rules:** 38 cases (illegal overrides, inheritance cycles, forward references, missing or badly typed params, misplaced or invalid `lag`, alias use before aggregation, calc collisions, division by zero, bad casts) all return the exit code I designed for them.
- **Part 1:** 15 old-style DSL files gave the same exit codes as the original code, under two timezones. Output was identical where they succeed. The only differences are error message wording in three files that now look like partly valid new syntax (`=`, `{`, `schema`), and those still return `bad_dsl`.

**What was added:**
- **Two file modes:** files with only Part 1 statements behave as before. Files with `schema`/`pipeline` blocks use the new rules.
- **Schemas:** inheritance; overrides allowed only for the same type or `int`→`float`; physical fields must be in the CSV, calculated fields are computed per row.
- **Calc statements:** `@stage(pre)` calcs run before filters; `@stage(post_agg)` calcs run on the sorted output rows in the order they are declared. `lag`/`lead` return `null` when there is no neighbouring row.
- **Params:** typed defaults, `--param key=value` (repeatable, last one wins), and `param("x")` can also set the window size, e.g. `'1h'`.
- **New expressi

## checkpoint_3
pass {'Core': 3, 'Functionality': 51, 'Regression': 98, 'Error': 10} / total {'Core': 3, 'Functionality': 52, 'Regression': 98, 'Error': 11}

**checkpoint_3-Functionality** (1 failed)
- `test_checkpoint_3_hidden[04_many_files]`: E           AssertionError

**checkpoint_3-Error** (1 failed)
- `test_checkpoint_3_edge_format_auto_ambiguous`: E       assert 0 == 3

**Agent final message:** All four requirements are implemented and working. I ran each case by hand on small mixed test files; there is no automated test suite.

**What I checked:**
- **The spec example:** run over a mix of CSV, TSV.GZ and Parquet files, it gives the expected totals. `NaN` prices become null and the filter drops them. Bad timestamps, empty timestamps, Parquet type mismatches and short rows are written to `--bad-records-out`, sorted by file then line.
- **Strict mode:** stops at the first bad row. It exits 2 for data/type problems and 4 for a pre-stage runtime error such as division by zero.
- **Order independence:** swapping the `--input` order gives byte-identical output.
- **Input handling:** directories (with and without `--recursive`), globs, the same file named twice (counted once), files with no extension, uppercase `.CSV.GZ`, STDIN, and corrupt gzip/Parquet files (exit 3).
- **Parquet timestamps:** timestamps stored without a timezone are read in `--tz` and converted to UTC.

**How it works:**
- **Inputs (`mtl_engine/inputs.py`):** combines all the `--input` arguments, removes duplicates and sorts by path. Directories and globs only pick up supported extensions, plus files with no extension.
- **Reading (`mtl_engine/loader.py`, replaces `csv_loader.py`):** reads CSV/TSV (gzip detected automatically) and Parquet, and converts every value to its schema type. A row that can't be converted is rejected with a classification instead of stopping the run.
- **Bad records (`mtl_engine/

## checkpoint_4
pass {'Core': 1, 'Functionality': 55, 'Regression': 116, 'Error': 4} / total {'Core': 1, 'Functionality': 57, 'Regression': 164, 'Error': 4}

**checkpoint_3-Regression** (2 failed)
- `test_checkpoint_3_edge_format_auto_ambiguous`: E       assert 0 == 3
- `test_checkpoint_3_hidden[04_many_files]`: E           AssertionError

**checkpoint_4-Functionality** (2 failed)
- `test_checkpoint_4_hidden[05_join_full_outer]`: E           AssertionError
- `test_checkpoint_4_regression[33_recursive_directory]`: E           AssertionError

**Agent final message:** I've extended `mtl.py` to cover the Part 4 spec. I tested it by hand against fixtures built from the spec's example (a Parquet web feed, a gzipped CSV POS feed and a promo feed) plus about 40 error and edge cases. All of them returned the expected exit code and a single `ERROR:<type>:<message>` line. There is no automated test suite in the repo, so none was added. The old `--input` mode still works as before.

**What's new:**
- **CLI:** a new `--ingest-config` flag that takes a YAML or JSON file. I added `PyYAML>=6.0` to `requirements.txt` and installed it into the existing `.venv`. Config errors exit with code 5 (`config_error`).
- **Config handling:** each source's settings are checked when the config is loaded. Files are found by glob, and a file matching several sources goes to the one with the lowest precedence number. A tie, or two sources declaring the same pattern at equal precedence, is a config error. Each source's file list is sorted by absolute path.
- **Per-source loading:** the mapping steps run in the spec's order (drop, rename, cast, defaults), then the row is checked against the source's DSL schema. Rows that fail are bad rows: they stop the run under `--strict`, otherwise they are dropped and written to `--bad-records-out`. Per-source `tz`, `nulls` and `format` override the CLI flags.
- **DSL:** `sources { … }`, `with Alias { … }` blocks, `A.col` column references, and joins with `within`, all four join types, `project { … }` and an optional `as` name. Chain

## checkpoint_5
pass {'Core': 1, 'Functionality': 19, 'Regression': 46, 'Error': 5} / total {'Core': 1, 'Functionality': 20, 'Regression': 48, 'Error': 5}

**checkpoint_5-Functionality** (1 failed)
- `test_checkpoint_5_hidden[03_join_full_outer]`: E           AssertionError

**checkpoint_5-Regression** (2 failed)
- `test_checkpoint_5_regression[11_null_aggregates]`: E       AssertionError
- `test_checkpoint_5_regression[33_recursive_directory]`: E           AssertionError

**Agent final message:** Part 5 is implemented. I checked it by hand on throwaway CSV, Parquet and gzip data; the repo has no test suite and I didn't add one. In those checks, a resume with no changes produced byte-identical output, and metadata identical apart from the run ID, timestamps and the `resume` flag. All the new exit-6 and exit-1 cases returned the right code with one stderr line.

**How resume works.** With `--state-dir`, each file is parsed once and the parsed result is saved in `<state-dir>/<pipeline>.checkpoints/`, keyed by its path, format and fingerprint. On `--resume`, a file whose fingerprint matches a `done` entry is loaded from that saved copy instead of being read again. Evaluation and aggregation then run over all files, which is why the output stays byte-identical. Some consequences:
- **Skips are real.** I edited a file but kept its size and mtime. With `mtime_size` the resume kept the old content. With `--fingerprint xxhash64` (which hashes `.gz` files after decompressing) it read the new content and updated the state.
- **Removed files** are dropped from the state on the next successful run.
- **Atomic writes.** The state file is written via temp file + rename, and only after output and metadata are written. A failed run (I tried a `--strict` failure) leaves the previous state untouched.
- **Exit 6** covers: no version header, a major version other than 1, `--resume` without `--state-dir`, a missing or malformed state file, a changed DSL or ingest config hash ("breaking cha
