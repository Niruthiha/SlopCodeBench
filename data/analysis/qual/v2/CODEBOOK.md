# Codebook: qualitative coding of SCBench Parnas-pilot traces (v2)

Written 2026-11-11 before coding. Navigation codes reuse `hotcrp-mask/analysis/BEHAVIOUR_DVS.md` section A
(text search, reading, following the code, docs, runtime, recall). New codes: throwaway probes, own tests,
reference library, memory notes. Counts of *how often* come from scripts (`analysis/qual/techniques.py`);
this codebook is for *why/how*, coded by agents from the traces, with evidence.

## Units

- **Cell** = one task × one condition (one run). Coded blind from a packet `P##` (condition label hidden).
- **Checkpoint session** = one fresh agent session. Codes L, I, R apply to checkpoints k ≥ 2 (changing existing
  code). Code V applies to every checkpoint.
- **Failed test** = a hidden test listed as `FIRST` in `results/checkpoint_k.md` (first checkpoint where it fails;
  marked `REGRESSION` when it passed earlier). Code F applies to each. Tests sharing one cause may be coded as one
  group, but every test id must appear.
- **Production code** = the program's own source files (not tests the agent wrote, not /tmp scripts).
- **Place** = a production file. In a single-file program, a place is a top-level function or class instead.

## Evidence rule (all codes)

No evidence, no code. Every code carries at least one evidence item:
`{"src": "trace" | "<packet-relative path>", "ck": k, "step": n | null, "line": n | null, "quote": "..."}`
- `src: "trace"`: `ck` and `step` are the `[ck.step]` tag in `trace_digest.md`. The quote is copied **verbatim** from
  that step's line (the call, its `->` result, or a `SAY:` line right before or after it), at most 200 characters.
- Other files (spec, diffs, code, results, tests): give the path and `line`. The quote is verbatim from that line.
- If the evidence does not exist, use code `UNCLEAR` with a one-line reason. Do not guess.

## L. Locating: how did the agent find where to make the change? (k ≥ 2)

For each place it edited, code the method by which that place was **first shown** in this session (the first call
whose output named or showed it). Also record `L_primary` = the method for the first production edit.

| Code | Definition | Example | Counting rule |
|---|---|---|---|
| L1 SEARCH | A text search (grep, rg, find with a pattern, Grep/Glob tool) printed the place. | `grep -n "def infer" pkg/*.py` → then edits `pkg/inference.py` | one per place |
| L2 LISTING | A listing without a content pattern (ls, tree, find without pattern) showed the file; it was then opened by name. | `ls pkg/` → `cat pkg/cursor.py` → edit | one per place |
| L3 READ-ALL | The agent read the program wholesale (whole single file, or all/most modules in one sweep) before editing; the place was seen during that sweep. | `cat *.py pkg/*.py` or Read of the whole 2,000-line file | one per place |
| L4 FOLLOW | Opened because code already read pointed to it: an import, a call, a registry/dispatch table. | reads `cli.py`, sees `from .report import render`, opens `report.py` | one per place |
| L5 DOCS | A docstring, module header, comment or README in the code pointed to it. | module docstring "Secret: how units are parsed" → edits that module | one per place |
| L6 RUN | Output of running the program or tests (traceback, wrong output) pointed to it. | traceback names `parser.py:212` → edits there | one per place |
| L7 RECALL | Edited or opened with nothing in this session having shown it first. | first call is `Edit pkg/x.py` | one per place |

## I. Interfaces vs internals: did it use other parts through their interfaces, or read and edit their insides? (k ≥ 2)

| Code | Definition | Example | Counting rule |
|---|---|---|---|
| I1 EXTEND | Most of the change is new functions/classes/branches; existing functions are changed only at a call or dispatch point. | adds `cmd_goto()` and one `elif args.cmd == "goto"` line | `I_primary`, one per checkpoint (I1 vs I2 by most changed lines in `diffs/`) |
| I2 MODIFY | Most of the change edits the bodies of existing functions. | rewrites the loop inside `resolve_name()` to handle a new case | as above |
| I3 CROSS-INTERNAL | (multi-file only) Code in one module reads or changes another module's private names (`_x`) or internal data structures, or the edit for this feature reaches into another module's internals. Single file: `NA`. | `from .scopes import _walk_nodes` in `inference.py` | flag yes/no per checkpoint + each instance |
| I4 INTERFACE-CHANGE | Changes the signature or return shape of an existing function/class used elsewhere, and updates callers. | `parse(src)` → `parse(src, tolerant=True)` and 3 callers edited | flag yes/no + instances |
| I5 READ-INTERNALS | Reads the bodies of modules/functions it then does **not** edit, to learn how they behave (vs signatures/docstrings only). Single file: code yes only for reading function bodies far from the edit. | `sed -n 1,400p pkg/introspect.py`, never edited | flag yes/no + evidence |

## R. Reuse vs copy: did it reuse existing code or copy it? (k ≥ 2)

| Code | Definition | Example | Counting rule |
|---|---|---|---|
| R1 REUSE | The new feature calls an existing helper instead of re-implementing it. | new `infer` command calls existing `find_scope()` | count instances |
| R2 COPY | Re-implements or copy-pastes logic that already exists elsewhere in the program. Evidence must name **both** places. | second tokenizer for `goto` next to the existing one | count instances |
| R3 EXTRACT | Moves existing code into a shared helper so old and new code both use it. | factors `_load_yaml()` out of two commands | count instances |

## V. Verification: how did it check its work? (every checkpoint)

Record every code present, plus `V_primary` (the one with the most calls in that session).

| Code | Definition | Example | Counting rule |
|---|---|---|---|
| V1 PROBE-TMP | Throwaway script or data written/run in /tmp. | `cat > /tmp/t.py <<EOF … EOF; python /tmp/t.py` | present yes/no; example |
| V2 PROBE-RUN | Ad-hoc runs of the program or `python -c` in the workspace. | `python sith.py complete f.py 3 4` | present yes/no |
| V3 OWN-TEST | Writes or runs its own unit tests (say which: write, run, both). | `python -m pytest tests/ -q` | present yes/no |
| V4 REF-LIB | Installs or inspects an existing library to compare behaviour or borrow facts. | `pip install jedi`, compares outputs | present yes/no |
| V5 SPEC-EXAMPLES | Runs the spec's worked examples and compares to the spec's stated output. | copies the example input from the spec, diffs output | present yes/no |
| V6 STATIC | py_compile, pyflakes, ast.parse, ruff, mypy. | `python -m py_compile *.py` | present yes/no |
| V7 REGRESSION-CHECK | Explicitly re-checks behaviour from earlier checkpoints after the change. | re-runs checkpoint-1 examples after adding checkpoint-3 feature | present yes/no |
| V8 MEMORY-NOTES | Writes notes or documents meant for later sessions (NOTES.md, DESIGN.md, design README). These were deleted before the next checkpoint. | writes `DESIGN.md` listing modules | present yes/no |

## F. Failed tests: was the cause a misread spec, or the code structure? (each FIRST failing test)

Read the test (`tests/`), the assertion output (`results/`), the spec for that checkpoint (`spec/`) and the code.
Pick **one** code. Precedence when several fit: F6 > F5 > F3 > F1 > F2 > F4.

| Code | Definition | Example |
|---|---|---|
| F1 SPEC-MISREAD | The spec states the expected behaviour (quote it with line), and the code contradicts it. | spec: "sort by name ascending"; output sorted by id |
| F2 SPEC-SILENT | The spec does not state, or is ambiguous about, what the test asserts; the agent's reading is defensible. | test expects a field the spec lists only as "may include" |
| F3 STRUCTURE | Caused by how the code is organised: a change made in one place but not a duplicate elsewhere; a change in one module broke behaviour owned by another; an interface change not propagated; the change made in the wrong layer. Name both places. | new flag handled in `cli.py` but the second copy of the parser in `batch.py` was not updated |
| F4 IMPL-BUG | A local logic error in the feature's own code, not about spec reading and not structural. | off-by-one in column handling |
| F5 UNFINISHED | The behaviour was never implemented, or the session ended/declared done without it. | `goto` on imports returns nothing; no code handles imports |
| F6 ENV | Crash from environment or packaging (missing dependency, import path, entry point), not program logic. | `ModuleNotFoundError: yaml` |

For REGRESSION tests, say what change at this checkpoint broke the earlier behaviour (cite the diff line).

## Reporting (comparison step, done later, from coded results only)

"In these runs we observed …", with counts and one example each. One run per condition per task: observations,
not effects of the prompt.
