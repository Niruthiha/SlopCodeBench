# techniques.py validation (hand-checked, 2026-11-11)

Population: 1,556 Bash calls across the 12 cells (all checkpoints). Edit/Write/Read/Grep tool calls are labelled by tool name and not sampled.
"Matched" = calls given at least one table label (probe_tmp, probe_run, own_test_run, edit_script); "unmatched" = everything else.
Each sample = 30 matched + 30 unmatched, fixed seed (techniques_sample.py <seed> <out>). A call is counted correct only if its whole label set is right.

| Round | Classifier | Seed | Matched correct | Unmatched correct | Total |
|---|---|---|---|---|---|
| 1 | v1 single-label (techniques_v1.py), then multi-label | 202611112 | 25/30 | 30/30 | 55/60 |
| 2 | after round-1 fixes (techniques_v2.py) | 7731 | 26/30 | 30/30 | 56/60 |
| 3 (held out, reported) | final techniques.py | 99173 | 27/30 | 30/30 | **57/60 (95%)** |

Round 1 errors: edit+probe in /tmp labelled probe_run instead of probe_tmp (#10, #14, #23); environment check (`pip list`) labelled probe_run (#19); probe after a test run missed (#9).
Round 2 errors: `/tmp/t/run.sh` probe missed (#10); `python -c "import yaml; print(version)"` as probe (#20); `ast.parse` syntax check and running a /tmp edit script as probe (#25); `pytest>=8.0` in requirements.txt and `-m venv` as test run / probe (#26).
Full-population effect of round-2 fixes: 12 calls lost own_test_run, all false positives (cat pytest.ini, `pytest.raises` inside test-file heredocs, the word unittest in a path); one heredoc `unittest.TestLoader` timing run added back.

Round 3 (held out, not used for tuning) errors, left unfixed so the figure stays honest:
- #7 `cd /tmp/agent_home/.claude/.../memory && cat MEMORY.md` labelled probe_tmp (memory read, not a probe).
- #21, #30 `python -c "import yaml"` / `python -c "import jedi"` availability checks labelled probe_run.
All three inflate probe counts by a small amount; no missed labels and no wrong test/edit labels in round 3.
Samples: techniques_sample.json, techniques_sample2.json, techniques_sample3.json.
