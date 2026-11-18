# Failure summary: runs/metric_transform_lang/c3_parnas_s1_20261109T1650

## checkpoint_1
pass {'Core': 4, 'Functionality': 25, 'Regression': 0, 'Error': 17} / total {'Core': 4, 'Functionality': 25, 'Regression': 0, 'Error': 17}

**Agent final message:** I've built the CLI. `mtl.py` is a thin entry point over a `mtl_core/` package, with a `.venv` virtual environment and a `requirements.txt` whose only dependency is `tzdata`, so `--tz` works on systems without a timezone database. I tested it by hand with about 40 cases: the full pipeline (window plus a two-column `group_by`), each error exit code 1–4, `--tz`, `--timestamp-format`, reordered CSV columns, CRLF line endings, empty input and stdin DSL. All behaved as intended. I didn't write an automated test suite.

**Design** (`DESIGN.md`): each module hides one decision that could change:
- **`dsl_parser.py`:** the DSL syntax (comments, multi-line `aggregate`, operator precedence) and the structural rules: exactly one `aggregate`, at most one `group_by`/`window`, unique aliases.
- **`expressions.py`:** type checking and evaluation of expressions, including round-half-away-from-zero and division-by-zero detection.
- **`aggregates.py`:** the math for each aggregate (median, population `std`/`var`, finiteness checks).
- **`timestamps.py`:** timestamp parsing, the default timezone and the UTC `Z` output format.
- **`windowing.py`:** epoch-aligned tumbling windows.
- **`csv_source.py`:** reading the CSV, typing the known columns and inferring types for extra columns.
- **`dataset.py`**, **`engine.py`**, **`output.py`** and **`errors.py`:** row storage, execution order, JSON ordering/encoding and the exit-code mapping.

The modules talk only through small interfaces; the syntax-tree

## checkpoint_2
pass {'Core': 3, 'Functionality': 37, 'Regression': 46, 'Error': 12} / total {'Core': 3, 'Functionality': 37, 'Regression': 46, 'Error': 12}

**Agent final message:** I've extended the Part 1 CLI with everything in the Part 2 spec: schema blocks with inheritance and overrides, calculated fields at both stages, pipeline parameters, and post-aggregation `lag`/`lead`. Both spec examples run and give the right key order (`window_start`, `window_end`, `location`, `category`, `avg_price`, `n`, `total_rev`, `prev_rev`, `rev_change`). Bare Part 1 programs with no blocks still work as before. I wrote about 40 ad-hoc checks covering every error case in the spec plus Part 1 programs, and all of them pass. There is no test suite in the repo, so these are my own checks, not the hidden tests. `requirements.txt` is unchanged because nothing new was needed.

**What's in place:**
- **Schemas:** inherit fields from their base. A child may keep a field's type or widen `int` to `float`; any other change exits 2. Cycles, unknown base schemas, multiple inheritance and duplicate names exit 1, and so do schema calcs that refer to unknown, later or self-referencing fields. When a schema is in use, the CSV must contain its non-calculated fields and those columns get the declared types; a missing column exits 3.
- **Calcs:** `@stage(pre)` calcs run per row before any filter or apply. Using an aggregate alias in one exits 1. Name collisions exit 1, and a declared type that doesn't match the expression exits 2. `@stage(post_agg)` calcs run after the final sort, in order, and are emitted sorted by name after the aggregate aliases. Referencing a per-row field in one exi

## checkpoint_3
pass {'Core': 3, 'Functionality': 51, 'Regression': 98, 'Error': 11} / total {'Core': 3, 'Functionality': 52, 'Regression': 98, 'Error': 11}

**checkpoint_3-Functionality** (1 failed)
- `test_checkpoint_3_hidden[04_many_files]`: E           AssertionError

**Agent final message:** The CLI now reads multiple files in CSV, TSV, gzipped CSV/TSV and Parquet, gives the same output whatever order the inputs arrive in, and rejects bad rows in a fixed, repeatable way. I tested it by hand against small messy fixtures and the results matched my own calculations. I did not write an automated test suite, and the repo has none.

**Spot-checked:**
- **Example pipeline:** the spec's `MixedIngest` example over a recursive directory holding a `.csv`, an upper-case `.TSV.GZ` and a `.parquet` gave the expected totals. `NaN` and `NULL` prices became null and the filter dropped those rows.
- **Messy rows:** the parse-type mismatch, timestamp parse error, short row and Parquet type mismatch rows were skipped and written to the bad-records file, sorted by file then line.
- **Strict mode:** the first bad record stops the run with exit 2, or 4 for runtime errors like division by zero. A referenced column missing from a file also gives exit 2; without `--strict` it reads as null.
- **Order:** passing the same `--input` arguments in different orders gives byte-identical output.
- **Parquet timestamps:** ones without a timezone are read in `--tz`; ones with a timezone convert to UTC.
- **Other options:** forced `--format`, glob inputs, DSL from stdin, `--nulls` replacing the defaults, and `lag()` after aggregation all work.

**Changes that affect earlier-part behaviour:**
- **Bad rows no longer stop the run by default.** Before, a bad value failed the whole run even without `--st

## checkpoint_4
pass {'Core': 1, 'Functionality': 55, 'Regression': 117, 'Error': 4} / total {'Core': 1, 'Functionality': 57, 'Regression': 164, 'Error': 4}

**checkpoint_3-Regression** (1 failed)
- `test_checkpoint_3_hidden[04_many_files]`: E           AssertionError

**checkpoint_4-Functionality** (2 failed)
- `test_checkpoint_4_hidden[05_join_full_outer]`: E           AssertionError
- `test_checkpoint_4_regression[33_recursive_directory]`: E           AssertionError

**Agent final message:** I've extended `mtl.py` with `--ingest-config`, so one run can load several named sources (web, POS, promos), join them, and then run the normal pipeline. The spec's own example runs and gives the right numbers. I also checked about 40 other cases by hand — every join type, chained joins, Parquet sources, strict mode and the error paths. The old `--input` mode works as before. These were ad-hoc runs; I haven't added a test suite to the repo.

**What's added**
- **Ingest config (YAML or JSON):** named sources, each with file patterns, format, schema, precedence, timezone, null markers, timestamp format, mapping (drop, then rename, then cast, then defaults) and required fields. A file matched by several sources goes to the lowest precedence number; a tie is a config error. Each source's files are sorted by absolute path.
- **Per-source checks:** each row is converted to its DSL schema (including inheritance, int→float widening and calculated fields), then the required fields are checked. Bad rows fail the run under `--strict`; otherwise they're dropped and written to `--bad-records-out` if given.
- **DSL:** `sources { web as W, ... }`, `with W { ... }` blocks, qualified names like `W.item`, `within 10m` (units s/m/h/d), the four join types, `project { ... } as WP`, and chaining through a join alias or `_`. Equality conditions in `on` use a hash join; a full join of 50k × 50k rows took about 4 seconds.
- **Exit codes:** the new `5`/`config_error` covers the cases in the spec. DSL

## checkpoint_5
pass {'Core': 1, 'Functionality': 19, 'Regression': 46, 'Error': 5} / total {'Core': 1, 'Functionality': 20, 'Regression': 48, 'Error': 5}

**checkpoint_5-Functionality** (1 failed)
- `test_checkpoint_5_hidden[03_join_full_outer]`: E           AssertionError

**checkpoint_5-Regression** (2 failed)
- `test_checkpoint_5_regression[11_null_aggregates]`: E       AssertionError
- `test_checkpoint_5_regression[33_recursive_directory]`: E           AssertionError

**Agent final message:** Part 5 is implemented: version gating, deterministic resume and the metadata file all work end to end. I checked them by hand against scratch fixtures; there's no automated test suite.

**Version header**
- The `mtl_version X.Y` line must be the first non-comment line.
- A missing header or a major version other than 1 exits 6.
- A malformed header (e.g. `mtl_version 1` or `1.5.1`) exits 1.
- After parsing, each construct is checked against the version it first appeared in (e.g. `join`, `sources` and `with` need 1.4; `count(col)` and `coalesce` need 1.3; schemas, params, calc, lag/lead need 1.2). Using one with a lower declared version exits 1 and names the construct.
- Higher minors such as 1.9 are accepted, and unknown statements still exit 1.
- When the declared minor is below 1.5, one `WARNING:version:...` line goes to stderr, only if the run succeeds.

**Resume (`--state-dir`, `--resume`, `--fingerprint`)**
- Each file is copied into `<state-dir>/<Pipeline>.snapshots/`, and the pipeline always reads the copy.
- On resume, files that are unchanged and marked done are read from their copy and never re-read from the original. Recomputing over the copies is what keeps output byte-identical, including for median, joins and lag.
- Modified or new files are copied again and processed. Files that are no longer discovered are dropped from the state.
- The state file has all required fields and is written atomically. A failed run leaves the previous state untouched.
- A missing or
