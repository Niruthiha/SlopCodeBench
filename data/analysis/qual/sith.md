# sith — qualitative comparison of c1 / c2 / c3 (seed 1)

Runs: `runs/sith/c1_default_s1_20261109T2346`, `runs/sith/c2_modular_s1_20261110T0220`, `runs/sith/c3_parnas_s1_20261110T1255`. Step ids are `[checkpoint.step]` from `analysis/qual/digests/sith__<cond>.md`. Call counts are from `analysis/qual/navstats.csv`.

## Summary

- c1 and c2 fail exactly the same 47 test instances (summed over ck1–6), and they have the same pass count at every checkpoint. c3 fails 32. All three pass 39/39 at ck1.
- The whole 15-instance gap comes from three checkpoint-2 tests that c1/c2 fail and c3 passes. Each is counted again at ck2–ck6 (3×5): `test_infer_implicit_none_for_no_return`, `test_infer_bare_return_yields_none` and `test_infer_none_narrowing_in_if_branch`. In all three, c1/c2 return `NoneType` where the test expects `None`.
- This difference can be traced to behaviour. c1 copied jedi's `NoneType` naming after installing jedi as a reference [2.6]–[2.8]. c2 took the name from the runtime `type(None).__name__` (`sithlib/inference.py:45`). c3 special-cased the name to `"None"` (`sithlib/navigation.py:706-708`), and in its ck2 final message it called this an ambiguity it had resolved.
- No visible step connects c3's `None` choice to the Parnas instruction. c3 also had jedi installed [2.9], and its comparison script mapped jedi's `NoneType` to `None`.
- The other 17 ck6 failures are shared by all three conditions: env discovery (fake executables), stub-vs-source goto preference, circular-import hiding, unresolved-name references, extract-variable output, `smart_sys_path`, and runtime namespace completion.
- Structure differed as instructed: c1 kept one growing `sith.py` (about 6,700 lines by ck6); c2 built a `sithlib/` package of 34 modules; c3 built 23 modules whose docstrings carry "Secret:" lines.
- Re-orientation was the same in all three: each fresh checkpoint began by dumping code with `cat`/`sed` through Bash. Search used Bash almost entirely, with zero Grep/Glob calls in any condition.
- Testing differed. c1 never wrote an automated test suite. c2 wrote tests from ck1 (23 → 97 tests). c3 wrote tests from ck2 (13 → 86). These suites caught nothing the hidden tests check differently: c2's own tests encoded `NoneType` [2.35].

## c1

**Navigation.** Every checkpoint re-reads the single file: whole-file `sed` chunks at [2.2]–[2.4], a grep'd list of `def`s plus Reads at offsets at [3.2]–[3.7] and [4.2]–[4.6], and `sed` ranges at [5.2]–[5.11] and [6.3]–[6.15]. ck3 had 26 calls and made no Edit/Write calls (navstats `pre_edit=26`).

**Search.** All search ran through Bash: `grep -n` for `def`/class names, plus `sed -n` line ranges. There were no Grep/Glob calls.

**Implementation.** ck1 wrote a 1,576-line `sith.py` in one Write [1.4]. At ck2 it drafted `/tmp/ref/partB.py` (2,347 lines) [2.12] and `partD.py` [2.13], then spliced them in with a Python script [2.14] (1,603 → 3,455 lines). Later edits were mostly Python `rep()` string-replace scripts run through Bash ([3.9] onward, [4.11]). ck5 again drafted a 1,301-line `/tmp/refactor_part.py` and spliced it in [5.12].

**Verification.** Testing was by hand through a `@@`-marker harness [1.7]–[1.18] and by jedi comparison [2.6]–[2.10]. It also ran old-vs-new completion diffs over the stdlib [2.23], [2.40] and a regression run over 4,797 positions with 0 diffs [4.37], after an attempt against the old `.pyc` failed [4.23]. The env commands were tested only against the real system pythons [6.31]. The ck1 final message says "No automated test suite was written".

**Struggles.** `sleep` was blocked [3.21]. It spent time on Monitor/TaskStop [4.32]–[4.38]. Its own output showed `infer:15:8 ['NoneType']` at [2.18] and [2.28], which matched jedi's `'full_name': 'builtins.NoneType'` [2.8]. *Interpretation:* using jedi as the oracle fixed the `NoneType` naming that the three ck2 tests reject.

## c2

**Navigation.** Each checkpoint opened with a `cat` of every module: [2.2]–[2.7] (first edit at [2.10]), [3.3]–[3.9], and [4.3]–[4.11], followed by repeated Reads of inference/navigation/definitions/members [4.12]–[4.15]. It checked for a memory directory at [4.2] and [5.1], but the memory written at [2.53]–[2.55] had not persisted.

**Search.** Bash only (`cat`, `grep`, `find`). There were no Grep/Glob calls.

**Implementation.** ck1 created 17 modules (cli, source, parsing, scopes, inference, completion, ...). Each later checkpoint added modules: flow.py [2.13], a rewritten inference.py (865 lines) [2.14], definitions.py [2.18] and navigation.py [2.19]; stubs/signatures/project/references/listing at ck4; refactoring/rename/inline/extract (648 lines)/syntax_errors at ck5; options/namespaces/enclosing/environments at ck6. ck3 rewrote modules.py [3.14] and touched seven other modules.

**Verification.** It wrote `tests/test_sith.py` at [1.31] (23 tests) and fuzzed about 750 positions [1.36]–[1.41]. The suite grew to 42 at ck2, 51 at ck3, 71 at ck4, 83 at ck5 [5.x "All 83 tests pass"] and 97 at ck6. At ck4 several of its own expectations had wrong columns [4.42]–[4.44]. For env, it created real venvs with `python -m venv --without-pip` [6.38].

**Struggles.** The ck2 output prints `"name":"NoneType","full_name":"builtins.NoneType"` [2.32]. A test failure at [2.35] shows "First extra element 0: ('NoneType', 'instance')", and the agent then aligned code and test on `NoneType` ([2.46] output `[('NoneType','instance'), ...]`). *Interpretation:* its self-written tests locked in the naming that the hidden tests reject. The name came from `NONE = RuntimeInstance(type(None))` (`checkpoint_2/snapshot/sithlib/inference.py:45`), not from jedi; c2 never installed jedi.

## c3

**Navigation.** Each checkpoint started with `cat` of all modules: [2.3]–[2.6], [3.3]–[3.4], [4.3]–[4.4] plus "navigation.py in full", [5.3]–[5.4], and [6.2]–[6.4]. ck3 made its first Write only at [3.30] (navstats `pre_edit=29`); earlier edits went through Bash.

**Search.** Bash only. There were no Grep/Glob calls.

**Implementation.** ck1 wrote 15 files [1.4]–[1.23], each with a "Secret:" docstring, plus `DESIGN.md` [1.48] listing the secrets. ck2 added flow.py [2.12], rewrote inference.py (1,280 lines) [2.14] and added navigation.py (714 lines) [2.16]. ck4 added signatures.py [4.23] and symbols.py [4.28]. ck5 put all four refactorings in a single 935-line refactoring.py [5.14], plus diagnostics.py [5.16]. ck6 added config.py [6.16], environments.py [6.17], interpreter.py [6.22] and enclosing.py [6.26]. At [4.x] it explained that a cursor change went in cursor.py because "its role is lexing text before the cursor".

**Verification.** It did hand checks through a `|`-marker driver [1.25] and fuzzing over stdlib files [1.36]–[1.47]. At ck2 it installed jedi in `/tmp/jediref` [2.9], compared against it [2.21], and ran sweeps of 2,738 runs with 0 errors [2.40] and 1,105 completions [2.49]. Test files: test_navigation (13 tests, ck2), test_imports (+13) [3.30], test_features (+16) [4.45], test_refactoring (+20) [5.29], test_interpreter (+24) [6.39]. For env, it built fake venvs with `pyvenv.cfg` [6.34].

**Struggles.** `sleep` was blocked [2.28] and a slow sweep was stopped [2.38]. Two test expectations at ck4 and one at ck6 were wrong (its own column choices). On `None`, the c3 ck2 snapshot `navigation.py:706-708` contains `if cls is type(None): return "None"`. Its jedi diff script normalised `d.name if d.name != "NoneType" else "None"` (stdout.jsonl, ck2). At [2.44] it called the remaining differences "cosmetic type names", and its ck2 final message lists "the `None` type is named `None` / `builtins.None`, not `NoneType`" as an ambiguity it resolved.

## Cross-condition comparison

| Question | c1 | c2 | c3 |
|---|---|---|---|
| Navigation | sed/Read chunks of one file | `cat` of every module per checkpoint | `cat` of every module per checkpoint |
| Search | Bash grep/sed; 0 Grep/Glob | same | same |
| Implementation | one file; large drafts spliced in [2.14], [5.12] | 17 → 34 modules | 15 → 23 modules with "Secret:" docs; 935-line refactoring.py |
| Verification | hand harness + jedi diff; no test suite | own suite 23 → 97 + fuzz | own suite 13 → 86 + jedi diff + sweeps |
| Struggles | `sleep`/Monitor handling; env tested on real pythons only | wrong own test columns; memory lost | wrong own test columns; `sleep` blocked |
| `None` naming (only differing outcome) | `NoneType` (copied from jedi) | `NoneType` (from runtime `__name__`) | `None` (explicit special case) |

The three runs were the SAME in how they re-oriented (bulk dump through Bash at the start of every fresh container), in using no Grep/Glob, in making most edits through Python replace scripts, and in failing the same 17 ck6 instances. c1 and c2 reached the same test outcome by different routes: one file without tests versus 34 modules with 97 tests. Shape differences follow the prompt wording (single file / modular / secrets). No visible step ties the one outcome difference, `None` vs `NoneType`, to the prompt. *Interpretation:* the outcome gap is one naming decision made at ck2 and carried forward, not a difference in architecture or verification effort.

## Failures traced to behaviour

- **`None` vs `NoneType` (c1, c2; 15 instances).** The spec (`scb-problems/sith/checkpoint_2.md`) says builtin definitions use "builtins.<name>" and that a missing return "is `None`". The tests assert `'None' in names` (`tests/test_checkpoint_2.py` ~190, 356, 399). c1 adopted jedi's output [2.8]. c2's own test [2.35] asserted `NoneType`. c3 overrode jedi [2.44].
- **`is not None` narrowing on an unannotated parameter (all).** `def f(x): if x is not None: return x` expects non-empty output; all three return `[]`. No condition probed an unannotated parameter narrowed this way that I could find in the digests.
- **Stub vs `.py` preference in goto (all).** All three returned `util.py` where `main.py` was expected; c3 at [4.x] says "Stubs behave as intended". *Interpretation:* each condition's own check encoded the same reading.
- **Env discovery (all, 6 instances).** The hidden tests build fake executables under `tmp_path` (`tests/test_checkpoint_6.py`). c1 tested only real system pythons [6.31]. c2 used real venvs [6.38]. c3 built fake `pyvenv.cfg` dirs [6.34], but still fails the same tests. Behaviour does not fully explain this one.
- **Circular import hiding, unresolved-name references, extract-variable diff, `smart_sys_path`, runtime namespace completion (all).** These are the same failures in all three, and I found no condition-specific step that addresses them.

## Caveats

- This is one seed per condition. A single naming choice accounts for the whole difference, so this run says nothing about an effect of the prompt.
- The digests truncate long tool outputs (`…(+N)`). Some steps, marked `[4.x]`/`[5.x]`, are cited from SAY lines without their step numbers.
- c1's ck4 failure summary was truncated. The equality of the c1 and c2 sets comes from `evaluation.json`.
- c3's jedi normalisation is quoted from raw `stdout.jsonl`, not from the digest.
- I did not rerun any tests or Docker.
