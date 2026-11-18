# Always-failing tests and defect-adjusted scores

Cells: c1_planning_s1_20261109T1341, c2_modular_s1_20261109T1352, c3_parnas_s1_20261109T1407, c4_performance_s1_20261109T1423

Defect tests (BENCHMARK_DEFECTS.md, 16 ids) are excluded in 'adjusted'; the benchmark itself is unmodified.

## Tests failing in EVERY cell (per checkpoint where collected)

- checkpoint 1: 4 failing in all cells; of these, defect tests: 4; NOT explained by a known defect:
    - (none)
- checkpoint 2: 9 failing in all cells; of these, defect tests: 9; NOT explained by a known defect:
    - (none)
- checkpoint 3: 14 failing in all cells; of these, defect tests: 14; NOT explained by a known defect:
    - (none)
- checkpoint 4: 16 failing in all cells; of these, defect tests: 16; NOT explained by a known defect:
    - (none)

## Scores (passed/total)

| cell | ckpt | all tests | adjusted | current-ckpt all | current adj | regression all | regression adj |
|---|---|---|---|---|---|---|---|
| c1_planning_s1_20261109T1341 | 1 | 28/32 | 28/28 | 28/32 | 28/28 | 0/0 | 0/0 |
| c1_planning_s1_20261109T1341 | 2 | 41/50 | 41/41 | 13/18 | 13/13 | 28/32 | 28/28 |
| c1_planning_s1_20261109T1341 | 3 | 18/68 | 18/54 | 13/18 | 13/13 | 5/50 | 5/41 |
| c1_planning_s1_20261109T1341 | 4 | 37/89 | 37/73 | 19/21 | 19/19 | 18/68 | 18/54 |
| c2_modular_s1_20261109T1352 | 1 | 28/32 | 28/28 | 28/32 | 28/28 | 0/0 | 0/0 |
| c2_modular_s1_20261109T1352 | 2 | 41/50 | 41/41 | 13/18 | 13/13 | 28/32 | 28/28 |
| c2_modular_s1_20261109T1352 | 3 | 18/68 | 18/54 | 13/18 | 13/13 | 5/50 | 5/41 |
| c2_modular_s1_20261109T1352 | 4 | 36/89 | 36/73 | 18/21 | 18/19 | 18/68 | 18/54 |
| c3_parnas_s1_20261109T1407 | 1 | 21/32 | 21/28 | 21/32 | 21/28 | 0/0 | 0/0 |
| c3_parnas_s1_20261109T1407 | 2 | 34/50 | 34/41 | 13/18 | 13/13 | 21/32 | 21/28 |
| c3_parnas_s1_20261109T1407 | 3 | 18/68 | 18/54 | 13/18 | 13/13 | 5/50 | 5/41 |
| c3_parnas_s1_20261109T1407 | 4 | 34/89 | 34/73 | 16/21 | 16/19 | 18/68 | 18/54 |
| c4_performance_s1_20261109T1423 | 1 | 26/32 | 26/28 | 26/32 | 26/28 | 0/0 | 0/0 |
| c4_performance_s1_20261109T1423 | 2 | 39/50 | 39/41 | 13/18 | 13/13 | 26/32 | 26/28 |
| c4_performance_s1_20261109T1423 | 3 | 51/68 | 51/54 | 12/18 | 12/13 | 39/50 | 39/41 |
| c4_performance_s1_20261109T1423 | 4 | 69/89 | 69/73 | 18/21 | 18/19 | 51/68 | 51/54 |
