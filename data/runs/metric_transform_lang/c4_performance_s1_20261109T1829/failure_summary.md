# Failure summary: runs/metric_transform_lang/c4_performance_s1_20261109T1829

## checkpoint_1
pass {'Core': 4, 'Functionality': 25, 'Regression': 0, 'Error': 17} / total {'Core': 4, 'Functionality': 25, 'Regression': 0, 'Error': 17}

**Agent final message:** I've written `mtl.py`, `DESIGN.md` and `requirements.txt`, plus a virtual environment in `.venv`. My regression script, `tests/run_tests.py`, passes all 36 checks on output values, exit codes, and the one-line `ERROR:<TYPE>:<Message>` format. The program uses only the standard library. `requirements.txt` lists `tzdata` as a fallback timezone database for machines that don't have one installed.

**How it's built for speed and memory**
- The DSL is type-checked first, then turned into one Python function tailored to the pipeline. That function runs over the CSV a row at a time, so the file is never loaded whole.
- A CSV field is only converted when it is first needed, so rows dropped by an earlier filter cost almost nothing.
- Columns that only need sum, average, min or max are periodically reduced to running totals, so memory stays bounded. Median and std/var keep their values (8 bytes per number on large files).
- Start-up imports are kept to a minimum. A tiny run takes about 36 ms, of which 17 ms is Python itself starting.

**Benchmarks on 1M rows (48 MB CSV)**

| Pipeline | Time | Peak memory |
|---|---|---|
| filter + apply + group_by + window | 2.1 s | 29 MB |
| global sum / average / median / std | 1.9 s | 65 MB |
| 1M distinct groups (worst case) | 7.5 s | 412 MB |

**Accuracy:** on the 1M-row file, sums, medians, var and std match Python's `statistics` module exactly. Averages are the sum divided by n, as the spec's "double-precision float semantics" suggests.

**Decis

## checkpoint_2
pass {'Core': 3, 'Functionality': 15, 'Regression': 46, 'Error': 12} / total {'Core': 3, 'Functionality': 37, 'Regression': 46, 'Error': 12}

**checkpoint_2-Functionality** (22 failed)
- `test_checkpoint_2_core_extended[06_string_ops_basic]`: E       AssertionError
- `test_checkpoint_2_core_extended[07_string_ops_with_params]`: E       AssertionError
- `test_checkpoint_2_core_extended[08_multiple_params_various_types]`: E       AssertionError
- `test_checkpoint_2_core_extended[09_type_widening_override]`: E       AssertionError
- `test_checkpoint_2_core_extended[10_multiple_pre_calcs]`: E       AssertionError
- `test_checkpoint_2_core_extended[11_multiple_post_agg_calcs]`: E       AssertionError
- `test_checkpoint_2_core_extended[12_post_agg_calc_simple]`: E       AssertionError
- `test_checkpoint_2_core_extended[13_lag_with_group_by_only]`: E       AssertionError
- `test_checkpoint_2_core_extended[14_window_group_lag_combined]`: E       AssertionError
- `test_checkpoint_2_core_extended[15_cast_basic]`: E       AssertionError
- `test_checkpoint_2_core_extended[16_regression_filter_apply]`: E       AssertionError
- `test_checkpoint_2_core_extended[17_regression_window_group]`: E       AssertionError
- `test_checkpoint_2_core_extended[18_regression_all_aggregates]`: E       AssertionError
- `test_checkpoint_2_file_output[02_complex_output]`: E       AssertionError
- `test_checkpoint_2_hidden[01_empty_input_with_calcs]`: E       AssertionError
- `test_checkpoint_2_hidden[02_single_row_lag_lead]`: E       AssertionError
- `test_checkpoint_2_hidden[03_lag_lead_large_k]`: E       AssertionError
- `test_checkpoint_2_hidden[04_multi_level_inheritance]`: E       AssertionError
- `test_checkpoint_2_hidden[05_coalesce_non_null]`: E       AssertionError
- `test_checkpoint_2_hidden[06_params_in_apply]`: E       AssertionError
- `test_checkpoint_2_hidden[07_same_type_override]`: E       AssertionError
- `test_checkpoint_2_hidden[08_param_timestamp_type]`: E       AssertionError

**Agent final message:** I've extended `mtl.py` with schemas, parameters, calcs and post-aggregation `lag`/`lead`. All 51 regression tests pass: the 36 original Part 1 cases plus 15 new Part 2 cases in `tests/run_tests.py`, which run against a new `tests/p.csv`. I also ran about 60 ad-hoc checks covering the spec's examples, every error case it lists, and edge cases. `requirements.txt` is unchanged because I only used the standard library.

**What's added**
- **Schemas:** single-parent `extends` blocks. Overrides may keep the same type or widen `int`→`float`; any other override exits 2. Circular inheritance, an unknown base, multiple parents, duplicate fields, and calculated fields that reference unknown or later-declared fields all exit 1. A physical field missing from the CSV exits 3, as in Part 1.
- **Parameters:** an optional `params { name [: type] [= default] }` block, set with `--param key=value` (repeatable, last one wins). A declared parameter with no default that isn't supplied exits 1; a value that doesn't parse to its type exits 2.
- **Calcs:** `calc name = expr : type @stage(pre|post_agg)`.
  - The declared type must match the expression (exit 2), except that an `int` expression may be declared `float`.
  - A pre-stage calc that references an aggregate alias exits 1.
  - Division by zero in any calc exits 4.
  - A post-agg calc that references a per-row field that isn't a group key exits 2.
- **New expression forms:** `param("x")` (double quotes are accepted only here, in `group_by` list

## checkpoint_3
pass {'Core': 3, 'Functionality': 51, 'Regression': 98, 'Error': 10} / total {'Core': 3, 'Functionality': 52, 'Regression': 98, 'Error': 11}

**checkpoint_3-Functionality** (1 failed)
- `test_checkpoint_3_hidden[04_many_files]`: E           AssertionError

**checkpoint_3-Error** (1 failed)
- `test_checkpoint_3_edge_format_auto_ambiguous`: E       assert 0 == 3

**Agent final message:** I've extended `mtl.py` to cover the Part 3 spec: multiple inputs, CSV/TSV (plain or gzipped) and Parquet, null markers, three-valued logic, and bad-record handling with `--strict` and `--bad-records-out`. The 51 existing regression tests still pass, plus 4 new Part 3 tests (55/55). I also checked by hand that:

- **The spec's example pipeline** produces correct results on a mix of `.csv`, `.csv.gz`, `.tsv`, `.tsv.gz` and Parquet files, including nested directories.
- **Order independence:** output is byte-identical when I shuffle the `--input` arguments. On 300k rows, with values spread across CSV, TSV and Parquet in shuffled order, results exactly match a single ordered file and an independent Python calculation.
- **Strict mode** stops at the first bad record in file-then-line order and writes just that record. Without `--strict`, bad rows are skipped and logged with all six error classifications.

`requirements.txt` now lists `pyarrow` (already installed in `.venv`; it's only imported when a Parquet file is read).

**Decisions you may want to revisit.** The spec was ambiguous on these, so I picked one reading:
- **`--csv` still works and keeps the old fail-fast behaviour.** Any error stops the run, and a missing column exits 3, so Part 1–2 callers keep their exit codes. `--input` follows the new rules, which means errors like division by zero in `apply()` now skip the row instead of exiting 4.
- **Missing columns:** without `--strict` they read as null. With `--strict` the

## checkpoint_4
pass {'Core': 1, 'Functionality': 55, 'Regression': 116, 'Error': 4} / total {'Core': 1, 'Functionality': 57, 'Regression': 164, 'Error': 4}

**checkpoint_3-Regression** (2 failed)
- `test_checkpoint_3_edge_format_auto_ambiguous`: E       assert 0 == 3
- `test_checkpoint_3_hidden[04_many_files]`: E           AssertionError

**checkpoint_4-Functionality** (2 failed)
- `test_checkpoint_4_hidden[05_join_full_outer]`: E           AssertionError
- `test_checkpoint_4_regression[33_recursive_directory]`: E           AssertionError

**Agent final message:** Part 4 is implemented in `mtl.py` and the extended regression suite passes 72/72: the 55 existing checks plus 17 new Part 4 ones in `tests/run_tests.py`. I added `PyYAML>=6.0` to `requirements.txt` and installed it in the existing `.venv`.

**What was added**
- **`--ingest-config`** (YAML, or JSON for `.json` files) declares named sources with patterns, `recursive`, `format`, `schema`, `precedence`, `tz`, `nulls`, `mapping` and `required`. A file matched by several sources goes to the lowest precedence number. A tie is exit 5. Each source's file list is sorted by absolute path.
- **Per-source ingestion** applies drop → rename → cast → defaults, then checks rows against the source's DSL schema (inheritance and int→float widening included), then the `required` fields. Failing rows are bad rows: dropped and logged to `--bad-records-out`, or fatal under `--strict`.
- **DSL additions:** the `sources { }` block, `with <Alias> { }` blocks (pre-stage calcs and filters only), and qualified names like `W.item`. Joins support `within Δ`, all four join types, `project { } [as Name]`, and chaining via a join alias, `_` or `(A ⋈ B)`.
- **Join execution** hashes on the equality conditions in `on` (nested loop otherwise). Outer joins fill the missing side with nulls. The projected relation then runs through the existing aggregation engine unchanged, so output format and ordering are as before.
- **Errors:** the spec's cases map to exit codes 1, 2, 3 and 5 as specified, each with a single `ER

## checkpoint_5
pass {'Core': 1, 'Functionality': 19, 'Regression': 46, 'Error': 5} / total {'Core': 1, 'Functionality': 20, 'Regression': 48, 'Error': 5}

**checkpoint_5-Functionality** (1 failed)
- `test_checkpoint_5_hidden[03_join_full_outer]`: E           AssertionError

**checkpoint_5-Regression** (2 failed)
- `test_checkpoint_5_regression[11_null_aggregates]`: E       AssertionError
- `test_checkpoint_5_regression[33_recursive_directory]`: E           AssertionError

**Agent final message:** Parts 1–4 behave as before, and the CLI now does version gating, deterministic resume and metadata output. All 91 regression tests pass: the 72 existing ones (now each with a version header) and 19 new Part 5 checks in `tests/run_tests.py`. On a 400k-row input the results are byte-identical to the old version and the added overhead is about 5%.

**Version header**
- The first non-comment line must be `mtl_version X.Y`. A missing header or an unsupported major version (2.x, 0.x) exits 6; a malformed header (`mtl_version 1.x`) exits 1.
- Using a construct that needs a newer minor than declared exits 1, e.g. `count(price)` under 1.2 or `join` under 1.3. Newer minors such as 1.7 are allowed if everything in the DSL is known.
- If a DSL older than 1.5 is run with `--meta-out` or `--state-dir`, one warning line goes to stderr and the exit code is still 0.

**Resume**
- State is written to `<state-dir>/<Pipeline>.state.json` with all the required fields, files sorted by path, and per-source watermarks. Writes are atomic, and a failed run leaves the old state untouched (tested).
- **How skipping works:** each processed file is copied into a snapshot store in the state dir. On `--resume`, a file whose fingerprint hasn't changed is replayed from its copy, not from the original. That keeps resumed output byte-identical even with joins and medians. I tested it by changing a file's content while keeping its size and modification time: `mtime_size` correctly skipped it and `xxhash64` repro
