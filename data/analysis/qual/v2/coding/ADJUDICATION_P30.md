# P30 failure-cause disagreements: adjudication (analyst, 2026-11-11, still blind to condition)

Coders agreed on 3 of 9 tests (fernite_carbide_te10 F1, split_days_over_thirty F2, ion_siege_real F2).
The 6 disagreements fall in 3 causes. Coder files are unchanged; this file records the adjudicated code.

| Tests | A | B | Adjudicated | Basis (packet P30) |
|---|---|---|---|---|
| ck5 kronos_invent, revelation_10_3d, loki_l1_1d; ck6 kronos | F1 | F2 | **F2** (B) | The spec contradicts itself. Rule (spec/checkpoint_5.md:18) splits only when time is `>` min(30, split_days), and the formula (line 25) `floor(split_days/days_per_run)` = floor(3/0.1) = 30 gives no split for 30 runs. But the example at split_days 3 splits Fernite Carbide 30 runs / 3.0 days into 2×15 (line 115; the same job is 1×30 at split_days 30, line 61). The agent chose strictly-under to match the example. Hidden tests follow the formula. |
| ck2 jackdaw-5 | F1 | F2 | **F1** (A) | B's premise is wrong: the data does list relics for Jackdaw. The test case gives `"relic_name_template": "Small {quality} Hull Section"` (tests/cases/checkpoint_2/jackdaw.json:8). The agent's "No relics found for 'Jackdaw'" (trace [2.9]) came from its own `relic_quality` prefix match `name.startswith(prefix)` (code/checkpoint_2/industry.py:364), not from the data. It then printed the Tech II layout for a Tech III item, against spec/checkpoint_2.md:43 (Tech III columns). |
| ck4 svipul_l1-1 | F4 | F2 | **F1** | Same root cause as jackdaw (prefix match misses "Small Malfunctioning Hull Section", tests/cases/checkpoint_4/svipul_l1/produce.txt:1). Coded F1 for consistency with jackdaw. A's F4 is also defensible (local bug); B's F2 rests on the same wrong premise as above. |

Summary: each coder was right on one of the two main causes. B was misled by the agent's own error message into reading a code bug as a data gap. A coded a self-contradictory spec as a misreading. Final P30: F1 ×3 tests (fernite, jackdaw, svipul), F2 ×6.
