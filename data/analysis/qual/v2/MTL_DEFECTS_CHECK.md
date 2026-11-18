# mtl candidate test defects: analyst check (2026-11-11)

Checked by hand against the spec files and test assets in `scb-problems/metric_transform_lang/`.
All 7 failures below occur identically in c1, c2 and c3 (same tests, same checkpoints; from evaluation/report.json).

| Test (first ck) | Spec says | Test expects | Verdict |
|---|---|---|---|
| 04_many_files (ck3) | checkpoint_3.md:194 "Rows with unparsable `timestamp` → dropped with `TIMESTAMP_PARSE_ERROR`." | `file10.csv:2` = `2025-09-14T08:010:00Z,100.0` counted: EXPECTED `{"n": 10, "total": 550.0}` | Contradicts spec |
| 05_join_full_outer (ck4), 03_join_full_outer (ck5) | checkpoint_4.md:174 a row whose post-`project` timestamp is null "cannot be windowed; such rows are **bad** (strict: fail; non-strict: drop)" | POS-only row (`orange`) projected via `W.timestamp as timestamp` (null) is kept and windowed: EXPECTED first row has `location: null, item: null, pos_total: 8.0` | Contradicts spec |
| 11_null_aggregates (ck5 regression) | checkpoint_1.md:173-175 no input rows → `count(*)` 0, "Other aggregates → `null`" | ck5 copy expects `"total": 0`; the ck4 copy of the same case expects `"total": null` (only change: `mtl_version 1.5` line added). checkpoint_5.md says nothing about empty-sum semantics | Contradicts spec and the earlier test |
| 33_recursive_directory (ck4, ck5 regression) | checkpoint_3.md:27 `--recursive` "Default: **off**"; checkpoint_4.md shows `recursive: true` in ingest config but states no default | ingest.yaml has no `recursive` key; EXPECTED `{"n": 3}` needs `data/sub/x.csv` (data/y.csv has 2 rows, sub/x.csv 1) | Spec gap; test assumes default on, opposite of the CLI default |

Consequence for coding: the coders' F2 codes for these 7 failures are consistent with this check. The first three rows are
test defects in the sense used for the defect-adjusted score; 33_recursive_directory is an unstated default. Benchmark tests
were not modified.
