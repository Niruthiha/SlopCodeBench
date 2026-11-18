#!/usr/bin/env python3
"""Always-failing tests across cells + scores with/without the 16 benchmark-defect tests (BENCHMARK_DEFECTS.md).
Usage: always_fail.py <run_dir>...  Writes runs/ALWAYS_FAIL.md and runs/scores_adjusted.json."""
import json, sys, os, glob
DEFECT = {f"test_checkpoint_1.py::test_hidden_cases[{c}]" for c in ("glob_case_sensitive", "glob_character_class", "glob_doublestar_crosses_dirs", "glob_question_mark")}
DEFECT |= {"test_checkpoint_2.py::test_extended_core_cases[verify]"} | {f"test_checkpoint_2.py::test_hidden_cases[{c}]" for c in ("multi_strategy_jobs", "strategy_sorting", "verify_complex_globs", "verify_no_files")}
DEFECT |= {"test_checkpoint_3.py::test_extended_core_cases[full_desto]"} | {f"test_checkpoint_3.py::test_hidden_cases[{c}]" for c in ("all_excluded_with_dest", "multi_jobs_different_dest", "verify_all_new", "verify_partial_unchanged")}
DEFECT |= {f"test_checkpoint_4.py::test_hidden_cases[{c}]" for c in ("exclusions_with_packs", "repack_after_exclusion")}
assert len(DEFECT) == 16
runs = sys.argv[1:]; res = {}; scores = {}
for run in runs:
    name = os.path.basename(run.rstrip('/')); scores[name] = {}
    for rp in sorted(glob.glob(os.path.join(run, '*/checkpoint_*/evaluation/report.json'))):
        ck = rp.split('/checkpoint_')[1][0]
        tests = {t['nodeid'].split('/')[-1]: t['outcome'] for t in json.load(open(rp))['tests']}
        for tid, o in tests.items(): res.setdefault((ck, tid), {})[name] = o
        p = sum(o == 'passed' for o in tests.values()); n = len(tests)
        d = [t for t in tests if t in DEFECT]; dp = sum(tests[t] == 'passed' for t in d)
        cur = [t for t in tests if t.startswith(f'test_checkpoint_{ck}.py')]; reg = [t for t in tests if t not in cur]
        def frac(ts): ts2 = [t for t in ts if t not in DEFECT]; return (sum(tests[t]=='passed' for t in ts), len(ts), sum(tests[t]=='passed' for t in ts2), len(ts2))
        scores[name][ck] = {'all': [p, n], 'adjusted': [p - dp, n - len(d)], 'defect_collected': len(d), 'defect_passed': dp,
                            'current': frac(cur), 'regression': frac(reg)}
always = sorted(k for k, v in res.items() if len(v) == len(runs) and all(o != 'passed' for o in v.values()))
L = ["# Always-failing tests and defect-adjusted scores", "", f"Cells: {', '.join(os.path.basename(r.rstrip('/')) for r in runs)}", "",
     "Defect tests (BENCHMARK_DEFECTS.md, 16 ids) are excluded in 'adjusted'; the benchmark itself is unmodified.", "",
     "## Tests failing in EVERY cell (per checkpoint where collected)", ""]
for ck in "1234":
    ids = [t for c, t in always if c == ck]
    L.append(f"- checkpoint {ck}: {len(ids)} failing in all cells; of these, defect tests: {sum(t in DEFECT for t in ids)}; NOT explained by a known defect:")
    L += [f"    - `{t}`" for t in ids if t not in DEFECT] or ["    - (none)"]
L += ["", "## Scores (passed/total)", "", "| cell | ckpt | all tests | adjusted | current-ckpt all | current adj | regression all | regression adj |", "|---|---|---|---|---|---|---|---|"]
for n, s in scores.items():
    for ck, v in s.items():
        c, r = v['current'], v['regression']
        L.append(f"| {n} | {ck} | {v['all'][0]}/{v['all'][1]} | {v['adjusted'][0]}/{v['adjusted'][1]} | {c[0]}/{c[1]} | {c[2]}/{c[3]} | {r[0]}/{r[1]} | {r[2]}/{r[3]} |")
open('runs/ALWAYS_FAIL.md', 'w').write("\n".join(L) + "\n")
json.dump({'scores': scores, 'always_fail': always}, open('runs/scores_adjusted.json', 'w'), indent=1)
print("\n".join(L))
