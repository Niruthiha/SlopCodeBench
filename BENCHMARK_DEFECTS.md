# file_backup: test/spec defects found during the Parnas pilot

Logged 2026-11-09. Benchmark: `scb-problems` @ 9cd9ca3 (origin github.com/gabeorlanski/scb-problems).
**Tests are NOT modified**: the benchmark stays as published. Scores are reported twice: on all tests, and
with the tests below excluded ("defect-adjusted"). Paths are relative to `scb-problems/file_backup/`.

Evidence of "always fail": in every agent run so far, these tests fail with identical counts and messages, while
the reference solutions pass every test (`runs/refcheck/`, pytest rc 0 at all 4 checkpoints).

## Defect 1: relative `--mount` resolved against an unspecified base (4 tests, checkpoint 1; regression at 2–4)

Tests: `test_checkpoint_1.py::test_hidden_cases[glob_case_sensitive | glob_character_class | glob_doublestar_crosses_dirs | glob_question_mark]`

- The 4 cases pass `--mount mount`, a relative path (`tests/data/checkpoint_1/hidden/glob_*/case.yaml:4`); the
  files are planted under `tmp_path/mount/` (`case.yaml:21+`).
- `run_case` calls `subprocess.run` with no `cwd` (`tests/test_checkpoint_1.py:57`), so the program runs from the
  workspace, not from `tmp_path`.
- `normalize_args` rewrites only tokens that exactly equal an input-file path (`tests/conftest.py:55-71`):
  `schedule.yaml` is rewritten to an absolute path; `mount` is not, because it is a directory, not an input file.
- The reference passes only because it resolves a relative mount against the schedule file's folder
  (`solutions/checkpoint_1/backup_scheduler.py:73-77`).
- The spec does not say this: "`--mount`: Path to the location where files are mounted. This should be treated as
  `mount://` root." (`checkpoint_1.md:16`). The standard reading (relative to the working directory) finds no files.
- These are the only 4 cases with a relative mount; e.g. `rel_mount` passes `{{static:files}}` (absolute).
- The tests are about glob matching, which the spec does specify fully (`checkpoint_1.md:62-64`); an agent can match
  globs correctly and still fail them. Observed: actual 4 events vs expected 6/8/8/7 (no files found).

## Defect 2: `verify` strategy must omit `total_size`, spec says the opposite (5 tests at checkpoint 2, 5 at checkpoint 3; regression after)

Checkpoint 2 tests: `test_checkpoint_2.py::test_extended_core_cases[verify]`,
`test_hidden_cases[multi_strategy_jobs | strategy_sorting | verify_complex_globs | verify_no_files]`.
Checkpoint 3 tests: `test_checkpoint_3.py::test_extended_core_cases[full_desto]`,
`test_hidden_cases[all_excluded_with_dest | multi_jobs_different_dest | verify_all_new | verify_partial_unchanged]`.

- Spec, checkpoint 2: "For `verify` strategy, output is identical except: `STRATEGY_SELECTED` has
  `"kind":"verify"`; `FILE_BACKED_UP` events become `FILE_VERIFIED`" (`checkpoint_2.md:136-138`). The example it
  refers to ends with `{"event":"JOB_COMPLETED",...,"total_size":0}` (`checkpoint_2.md:133`). Elsewhere
  `total_size` is only "may include" (`checkpoint_2.md:60, 83`).
- Spec, checkpoint 3: `JOB_COMPLETED` "May include `packs`, `total_size`, ..." (`checkpoint_3.md:98`); first run
  "Output is identical to checkpoint 2, with two new fields" (`checkpoint_3.md:132`).
- Expected outputs omit `total_size` for every verify job (e.g. `tests/data/checkpoint_2/core/verify/expected.jsonl`,
  `tests/data/checkpoint_3/core/full_desto/expected.jsonl`), while full-strategy jobs in the same case keep it
  (`checkpoint_3/hidden/multi_jobs_different_dest`: alpha-job has `total_size`, verify beta-job does not).
- Comparison is exact dict equality (`tests/conftest.py:226-234`), so an extra field fails.
- The reference solution's own unit test is named `test_verify_strategy_reports_zero_total_size` but asserts
  `"total_size" not in completed` (`solutions/checkpoint_2/tests/test_backup_scheduler.py:452, 496`), i.e. the
  intended behaviour changed and the spec was not updated.
- Observed: every failing case differs only by `'total_size': N` on a verify job's `JOB_COMPLETED`.

## Defect 3: `pack` at checkpoint 4 must emit every `FILE_EXCLUDED` before any `FILE_SELECTED`; spec says path order (2 tests, checkpoint 4)

Tests: `test_checkpoint_4.py::test_hidden_cases[exclusions_with_packs | repack_after_exclusion]`

- Spec: "For each job, process files in the source directory tree in lexicographic order by full relative path."
  (`checkpoint_1.md:97`); the checkpoint 1-2 examples interleave `FILE_SELECTED` and `FILE_EXCLUDED` in path order
  (`checkpoint_1.md:174-180`, `checkpoint_2.md:126-129`). Checkpoint 4, first run: "Behavior identical to checkpoint 2
  pack strategy." (`checkpoint_4.md:82`). No checkpoint-4 example has exclusions; no text changes the order.
- Expected outputs put all exclusions first: `tests/data/checkpoint_4/hidden/exclusions_with_packs/expected.jsonl`
  (C, E excluded, then A selected), `.../repack_after_exclusion/expected.jsonl` (B excluded, then A selected).
- The reference changed between checkpoints: checkpoint 2 emits per file in one loop
  (`solutions/checkpoint_2/scheduler/executor.py:146-162`); checkpoint 4 pack does an exclusion pre-pass, then emits
  `FILE_SELECTED` while walking the pack plan (`solutions/checkpoint_4/scheduler/executor.py:300-329`).
- Checkpoint 2 pack tests with exclusions (`pack_no_files`, `pack_single_large_file`) cannot tell the two apart: there
  every excluded path sorts before every selected one. These 2 checkpoint-4 cases are the first where they differ.
- Observed (all 4 pilot cells, identical): `Event mismatch at index 4: FILE_SELECTED A != FILE_EXCLUDED C` (resp. B).

## Checked and NOT a defect

- `test_checkpoint_3.py::test_missing_destination_is_rejected` (failed in the gate c1 run): the spec is explicit,
  "The `destination` field is now required." (`checkpoint_3.md:32`). Pilot c1 passed it. A genuine agent error.
- Non-`backup://` destinations rejected at checkpoint 3 (P3b pilot: c1, c2, c3 = 45 regression failures each;
  c4 accepted them). 53 checkpoint 1-2 cases use `destination: ignored://sink` (the checkpoint 1 example says "Unused
  right now", `checkpoint_1.md:39`). Checkpoint 3 makes `destination` required and shows only `backup://store`
  (`checkpoint_3.md:27, 32`); it does not say what other schemes do. A spec GAP, not a contradiction: rejecting is a
  reading the spec allows, and accepting is too. Kept in the scores; flagged because 3/4 cells took the same reading
  and it dominates checkpoint 3-4 regression. User to decide whether to report a sensitivity score without it.

## Excluded set used for "defect-adjusted" scores

16 test ids: 4 (defect 1) + 5 + 5 (defect 2) + 2 (defect 3, added after the P3b pilot). Each is excluded wherever it is collected, including as a regression
test at later checkpoints. (Earlier count "9" covered checkpoints 1–2 only; checkpoint 3 adds 5 of the same defect 2.)

## Upstream issue (draft, NOT posted: ready to submit in UPSTREAM_ISSUE_file_backup.md)

Title: file_backup: 16 tests encode behaviour the spec does not state (relative --mount base, verify total_size, pack exclusion order)
Body: the two sections above, with file:line references and the reference unit-test contradiction.
