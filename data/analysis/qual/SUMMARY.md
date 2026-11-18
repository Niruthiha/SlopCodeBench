# Qualitative trace analysis — cross-task summary (2026-11-11)
Per-task reports: sith.md, eve_industry.md, recli.md, metric_transform_lang.md (written by one subagent per task from digests/;
spot-checked by the orchestrator: sith None/NoneType, eve relic prefix + Science-group filter, recli first-run message). Counts: navstats.csv.
One seed per cell: everything below is what happened in these runs, not a measured effect.

## Same in all 12 cells
- Re-orientation: each checkpoint opens with ls/find then bulk cat/sed of most of the code; Grep/Glob tools never used; no README/docs read.
- Editing: mostly Python string-replace scripts or heredoc rewrites run through Bash; Edit tool rarely used.
- Calls before first edit per checkpoint: similar range across conditions (no consistent ordering).
- Every checkpoint ends with the agent declaring the spec done; hidden tests then fail.
- No agent refers back to its ck1 design instruction after ck1.

## Differs by condition (visible in traces)
- Shape: c1 one growing file (sith ~6.7k lines, recli 4.4k, mtl 4.4k, eve 1.1k); c2 a package; c3 a package with a "Secret:" per module (recli c3 also wrote a DESIGN.md decision table at ck1, which the harness's per-checkpoint agent-doc deletion removed from ck2 on, as designed).
- Spread of edits: c2/c3 touch many more files per extension (recli ck2..8: 4 / 29 / 34 files); c1 re-reads its one file in slices.
- Own tests: c1 never wrote a suite; c2 and c3 did in sith and recli (recli ends 208 / 217 own tests); in eve and mtl no condition wrote unit tests.
- Interface discipline (mtl): c2 called another module's private function; c3 added public helpers instead.

## What the failures trace to
- Almost all are spec readings, shared or not: sith None vs NoneType (all of c3's 15-instance advantage); eve job-split rule (shared), relic prefix (c1), Science-only skills (c2+c3), TE on reactions / waste definition (ck3 split three ways); recli first-run success line + docker gate in front of every command (all three; c2/c3 saw it in their own suites and changed fixtures, not behaviour).
- mtl shared failures look like test/data faults (malformed timestamp, expectations contradicting spec) — candidate defects, not yet verified.
- No failure in any task was traced to a structural slip (bypassed interface, duplicated logic). Condition-unique failures are local bugs (recli c1 YAML subset parser, c2 config append bug, c3 debug label/--color).
