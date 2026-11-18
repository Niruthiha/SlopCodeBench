# metric_transform_lang — qualitative trace analysis (c1_planning / c2_modular / c3_parnas, seed 1)

Runs: `runs/metric_transform_lang/c1_planning_s1_20261109T1458`, `c2_modular_s1_20261109T1557`, `c3_parnas_s1_20261109T1650` (c3 `_invalid_attempt/` ignored; c3 ck5 was resumed after an auth failure). Measured numbers come from `analysis/compare/data.json`. Step ids refer to `analysis/qual/digests/metric_transform_lang__<cond>.md`.

## Summary

- All three runs end at 71/74. Ck1 and ck2 pass fully in every condition. Ten of the failing instances are the same three test families in all three conditions: `04_many_files`, `join_full_outer` and `33_recursive_directory`, plus `11_null_aggregates` at ck5. The evaluation logs show identical actual values in each condition (`actual = 9, expected = 10`; `2` vs `3`; `None` vs `0`).
- I compared each shared failure with the spec and the test assets. Each one is a conflict between the test and the spec or its data, not a slip by the agent: `file10.csv` has a malformed timestamp `08:010:00Z`; checkpoint_4.md:174 says rows with a null timestamp after `project` are bad and are dropped; ck3 says recursion defaults to off; checkpoint_1.md:167 says aggregates over empty input are `null`. This is my reading of the assets, and the tests were not re-run.
- The only failure tied to a difference between conditions is c2's `test_checkpoint_3_edge_format_auto_ambiguous`, which accounts for 2 of c2's 9 failed instances. c2 chose to sniff the content of files with no extension ([3.21] `sniff: { "n": 2 }`) and so exited 0 where the test expects 3.
- Ck1 design: c1 kept one file, `mtl.py`, at every checkpoint (873→4,379 SLOC, cc_max 52). c2 built `mtl_engine/` (16→27 files, cc_max 37). c3 built `mtl_core/` (14→24 files, cc_max 48), and every module docstring names a "Secret:".
- Re-orientation looked the same in all three. Each checkpoint opened by reading the entire codebase (`cat` or Read of every file) before the first edit, which came after 6–12 steps in every condition. Only c1 used grep as a navigation aid, over its own `# ----` section markers ([3.6], [5.3]).
- Verification looked the same in all three: hand-made bash fixtures under `/tmp`, a copy of the previous checkpoint's code kept for regression diffs, and no unit-test files. Every ck3–ck5 final message says the work is done, and hidden tests then failed.
- The structures held up differently in the code itself. c1 grew by splicing big blocks in with python string-replace scripts (a 36 KB ingest section at [4.14]). c2 had one interface bypass: `ingest` calls the private `inputs._scan` ([4.15]). c3 added public helpers instead and kept updating its "Secret:" docstrings ([3.16], [3.17], [4.15]).
- None of the agents cited the ck1 modularity or information-hiding instruction after ck1. I found no trace evidence that the prompt drove any later behaviour.

## c1

**Navigation.** Every checkpoint begins with a whole-file read: [2.2] `cat mtl.py` plus [2.3] Read, [3.3]/[3.4] paged Reads, [4.3]–[4.5] paged Reads at offsets 700 and 1600, and [5.2] plus [5.5]–[5.8]. From ck3 on, the agent jumped around with `grep "^# ----"` section markers ([3.6]) and `grep "^def|^class"` ([5.3]). The first source edit came at [2.7], [3.8], [4.8] and [5.11]. Interpretation: in a single file, the section banners served as the module map.

**Search.** Search consisted of reading files plus two structural greps and one grep for `udf` ([5.4]). I found no dead-end searches. At ck5 it tried to `cat MEMORY.md` ([5.1]) and the file did not exist.

**Implementation.** At ck1 it wrote DESIGN.md ([1.2]) and then all of `mtl.py` in one 1,061-line Write ([1.3]). At ck2 it did a full rewrite: a 2,019-line Write ([2.7], "full rewrite, keeping Part 1 code paths intact"). Ck3–ck5 were spliced in with python `replace`/`rep()` scripts guarded by assert-counts ([3.8]–[3.13], [4.8]–[4.17], [5.11]–[5.19]), and new sections were sometimes staged in `/tmp` first ([3.7]). By ck4 the file had its own fallback YAML parser `MiniYaml` ([4.14]) and by ck5 a pure-Python XXH64 ([5.19]). The file stayed at 1, and cc_max rose from 37 to 52.

**Verification.** Ck1 ran about 40 ad-hoc cases ([1.4]–[1.6]). Each later checkpoint started by saving a backup of the previous code (`/tmp/mtl_part1.py` [2.5], `/tmp/mtl_part3_backup.py` [4.7], `/tmp/mtl_part4_backup.py` [5.10]) and ended with an old-vs-new diff ([2.8] "P1 OK", [4.23] "SAME", [5.25]–[5.27]). Other checks: a 3,000-row shuffle test for order independence ([3.17]), pyflakes ([3.22]), and FallbackYAML compared against PyYAML ([4.22]). It caught its own error when a splice failed with exit 1 ([5.18]).

**Struggles.** No loops. At ck4 it tested that a full join "gives the right count(col) nulls" ([4.19]) but not the case where only P has a timestamp. All of c1's failures fall into the shared families (see below).

## c2

**Navigation.** It read close to the whole package at every checkpoint: [2.2]–[2.5] (`wc` and then `cat` of all remaining modules), [3.2]–[3.5], [4.2]–[4.7], [5.2]–[5.10]. The first source edit came at [2.8], [3.8], [4.8] and [5.13]. Interpretation: having modules did not shorten the reading. The agent read all of them before touching any one.

**Search.** It searched by `cat`, with almost no grep. The same modules were re-read at every checkpoint, which is expected given fresh containers. I found no dead ends.

**Implementation.** At ck1 a thin `mtl.py` sat on top of `mtl_engine/` (cli, lexer, parser, ast_nodes, typecheck, evaluator, functions, aggregates, pipeline, output, csv_loader, dtypes, errors, timeutil), and the modules were written one at a time via heredocs ([1.3]–[1.10]). Each extension touched many files:
- ck2 changed lexer, ast_nodes, functions, parser ([2.13]–[2.15]), typecheck (rewritten, [2.17]), csv_loader, evaluator, pipeline (rewritten, [2.23]), output and cli, and added casts, schema and params ([2.12], [2.16], [2.19]).
- ck3 added `inputs.py` ([3.8]) and `badrecords.py` ([3.9]), and `loader.py` replaced csv_loader ([3.11]).
- ck4 added `ingest.py` ([4.14]) and `joins.py` ([4.20]) and edited six existing modules.
- ck5 added versions, udfs, state and metadata.

It removed duplication at [2.20] (int/float/bool parsing was "duplicated across three modules", moved into dtypes) and again in cli at [4.29]. It also introduced one bypass: `ingest` calls the private `inputs._scan` ([4.15]).

**Verification.** All testing used ad-hoc fixtures. It ran 38 error cases ([2.28]), checked Part 1 against a copy of the old tree ([2.7], [2.30]), and ran pyflakes ([5.27]). It caught a quoted `group_by` spec example failing ([2.25]→[2.26]) and a typing bug with `count(col)` on non-numeric columns ([3.18]–[3.19]).

**Struggles.** At [3.15] an `rm -rf` was blocked as a "Dangerous rm operation", and it rebuilt the fixture another way ([3.16]). At [3.21] it implemented and checked content sniffing for files without an extension, which is the cause of the c2-only failure (see below).

## c3

**Navigation.** It read all modules at each checkpoint ([2.3]–[2.6], [3.2]–[3.7] including `sed` ranges of the parser, [4.2]–[4.8], [5.2]–[5.10]). At [2.7] it also searched the filesystem for other `mtl`/DESIGN.md copies. The first source edit came at [2.8], [3.8], [4.11] and [5.13].

**Search.** Search was by `cat` and `sed`. At [2.19] it wrote a decisions note to the Claude memory directory, but memory does not persist across containers: at ck4 the `cat MEMORY.md` failed ([4.1]), and it wrote another at [5.38].

**Implementation.** At ck1 it wrote `mtl_core/` with modules errors, valuetypes, timestamps, dataset, csv_source, program, dsl_parser, expressions, aggregates, windowing, engine and output. Quoted secrets (from module docstrings):
- dsl_parser: "Secret: the concrete syntax of the DSL -- tokens, comments, how statements are delimited…"
- engine: "Secret: the execution strategy -- row steps run in program order…"
- errors: "Secret: how failure categories map to exit codes and how the diagnostic line is formatted."
- program.py describes itself as the "shared vocabulary between the parser and the engine".

Ck2 rewrote program, the parser (via `/tmp/parser_new.py`, [2.9]) and the engine ([2.13]), and cc_max rose from 23 to 52. Ck3 added quality, inputs and `sources.py` ([3.12]), which replaced csv_source (removed at [3.18]), and updated the secret docstrings ([3.16], [3.17]). Ck4 added `ingest.py` (648 lines, [4.16]) and `joins.py` ([4.18]), refactored declarations ([4.14]), and exposed a public `cast_value` and a reusable glob expander ([4.15]). Ck5 added versioning, udfs, fingerprints, checkpoints and metadata, and rewrote `mtl.py` at 307 lines ([5.26]). Like c2, each extension edited several modules.

**Verification.** All testing used ad-hoc fixtures. At ck1 it caught a bug in its own test CSV ([1.13]) and fixed deep nesting ([1.15]). At ck4 it tested that a null timestamp after project is dropped ([4.28], "null ts dropped") and timed a 50k×50k join at 3.8 s ([4.30]). Its test harness itself had bugs at [4.22] (run.sh args) and [5.32].

**Struggles.** An `rm` was blocked at [4.20]. Ck5 was interrupted by the auth failure and resumed, so the ck5 diff numbers (5,792 added / 0 removed) are a resume artifact.

## Cross-condition comparison

| Question | c1 | c2 | c3 |
|---|---|---|---|
| 1 Navigation | Whole-file Read, then section-marker grep; first edit after 6–10 steps | `cat` of whole package; first edit after 7–12 steps | `cat` of whole package; first edit after 7–12 steps |
| 2 Search | Read plus 3 greps; no dead ends | `cat`; no greps for navigation | `cat`/`sed`; failed memory-file lookup [4.1] |
| 3 Implementation | 1 file; full rewrite at ck2; splice scripts; cc_max 52 | 27 files; edits spread across modules; dedupe [2.20]; bypass `_scan` [4.15]; cc_max 37 | 24 files; secrets maintained; public helpers [4.15]; rewrites at ck2; cc_max 48 |
| 4 Verification | Ad-hoc plus old-version diffs | Same | Same |
| 5 Struggles → failures | Only the shared conflicts | Shared conflicts + sniffing choice (2 instances) | Only the shared conflicts |
| 6 Differences | Code shape only | Code shape + one spec reading | Code shape only |

The agent's process was the SAME in every condition: read everything, stage edits with python string-replace or heredocs, test with ad-hoc fixtures, diff against a saved copy, and declare done. The differences are in the shape of the code: one file versus 24–27 files, cc_max of 52/37/48, and in c3 an interface that kept its secrets documented. The only difference in outcomes is c2's spec reading on extension-less inputs. One seed per cell, so these are observations from these runs, not effects.

## Failures traced to behaviour

- **ck3 hidden `04_many_files` (all conditions).** `tests/assets/checkpoint_3_hidden/04_many_files/file10.csv` holds `2025-09-14T08:010:00Z`. All three implementations reject that timestamp as a bad record, which gives n=9 where 10 is expected. My classification: a test-data defect, not a behaviour difference.
- **ck4 hidden `05_join_full_outer` / ck5 hidden `03_join_full_outer` (all).** The expected output keeps a row present only in POS, with `location`/`item` null, inside a window. checkpoint_4.md:174 says a row with no `timestamp` after `project` "cannot be windowed; such rows are **bad**". c3 explicitly implemented the spec rule ([4.28]). Classification: the spec and the test conflict.
- **ck4/ck5 regression `33_recursive_directory` (all).** The ingest config lists `inputs: ["data"]` with no `recursive:` key, yet the test expects the subdirectory to be read. Ck3 spec: recursion default is "**off**". Classification: the spec and the test conflict.
- **ck5 regression `11_null_aggregates` (all).** The test expects `total: 0` for `sum` over zero rows. checkpoint_1.md:167 says non-count aggregates on empty input → `null`, and the earlier versions of the same case passed with null. Classification: the spec and the test conflict.
- **ck3/ck4 `test_checkpoint_3_edge_format_auto_ambiguous` (c2 only).** A file named `input` with no extension and default `--format auto` must exit 3. c2's content sniffing ([3.21]) produced `{"n": 2, "total": 3.0}` and exit 0. checkpoint_3.md:28 calls extension-less files "ambiguous" and says to force the format. Classification: a spec misreading (an added feature) that is visible in the trace. Nothing shows a link to the modular prompt.
- None of the failures in this task are structural slips (a change missed in one place) or features never attempted.

## Caveats

- One seed per condition, so no effect claims are possible.
- I classified the failures from the evaluation `actual`/`expected` lines, the test assets and spec greps. I did not re-run any code.
- I took the steps-before-first-edit counts from the first `Edit`/`Write` or writing Bash call that targets the workspace. Staging writes to `/tmp` are not counted, and the counts are approximate.
- c3's ck5 was resumed after an auth failure, which distorts its ck5 diff numbers.
- The c1 prompt here is c1_planning (DESIGN.md asked of all three), so c1 is not a no-guidance baseline.
- The memory files written by c3 ([2.19], [5.38]) did not persist, and I saw no effect from them.
