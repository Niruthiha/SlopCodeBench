# eve_industry — qualitative trace analysis (c1 / c2 / c3, seed 1)

## Summary
- **Structure.** c1 put everything in one file, `industry.py`, which grew to 1,129 lines by ck6. c2 built an `eve_industry/` package of 11 modules, and `plan.py` (528 lines) became the largest. c3 wrote 6 top-level modules in ck1, each with a one-sentence "secret" in its docstring, and had 12 by ck6. `planner.py` (377 lines) became its largest, and the CLI `industry.py` grew to 209 lines.
- **Re-orientation was the same in every condition.** Each checkpoint opened with `ls`, a memory-dir probe and then `cat` of whole files. c2 and c3 cat'd nearly every module at every checkpoint ([4.2–4.3] c2, [6.3–6.4] c3). No condition used Grep/Glob tools on its own code, and none read a README or docs. Steps before the first edit were similar outside ck2 (c1 3–7, c2 5–8, c3 3–7). At ck2 c2 took 13 and c3 took 14, against 6 for c1, mostly on SDE exploration.
- **Verification was the same in every condition.** Each agent diffed its output against the spec examples verbatim, ran a sweep over the SDE for crashes and hand-probed edge cases. None wrote unit tests. All three claimed byte-exact matches with the spec examples at every checkpoint.
- **Failed instances by root cause.** All of the failures (22 / 27 / 37) come from a few interpretation choices, and regression re-counting multiplies each one. A ck2 miss is counted 5 times and a ck3 miss 4 times.
- **Shared by all three (8 instances each).** All three adopted the same "strictly less than split_days" job-split rule, inferred from one spec example (7 instances). All three also show the same ion_siege_real datacore `end_amount` mismatch (1 instance).
- **Unique to c1 (8 instances).** Relic detection uses `name.startswith("Intact"/…)`, so `Small … Hull Section` relics are missed. This fails Jackdaw at ck2 and the Svipul build string at ck4. c1's own sweep surfaced the four tactical destroyers [2.9], and it explained them away as "invented from Tech I blueprints" [2.10].
- **Shared by c2 and c3 (15 instances each).** Both counted only skills in the SDE "Science" group in the probability formula. This excludes `Capital Ship Construction`, so Dual Giga fails and the clamp-to-100 % test fails. Both stated this choice in their ck2 summaries. c2 tried to test clamping [2.19], the probe broke, and it ended the checkpoint without retrying.
- **ck3 ambiguities split differently.** c1 and c2 assumed TE does not apply to reactions and fail `fernite_carbide_te10` (4 instances each). c3 applied TE to reactions and passed that test. c3 instead defined waste as `qty(ME0) − qty(ME)`, which matches the spec's only waste example by coincidence, and fails 3 waste tests (12 instances).
- **split_days > 30.** c1 and c3 capped values above 30, citing the spec's `min(30, split_days)`. c2 rejected them, and only c2 passed `test_split_days_over_thirty_fails`.
- **No failure is clearly a structural slip** (a bypassed interface or code duplicated in the wrong place). Every hidden-test failure goes back to a spec reading or a data-classification heuristic.

## c1
**Navigation.** At each checkpoint c1 ran `ls`, then `cat industry.py` or Read the whole file ([2.2], [3.2], [4.2], [5.3]+[5.4], [6.3]). At ck5 the cat output was too large (34.7 KB, [5.3]), so it re-read the file with Read [5.4]. It probed `/tmp/agent_home/.claude/.../memory` at ck3–6 and found nothing ([3.1], [4.1], [5.2], [6.2]). It made its first edit after 6 / 3 / 3 / 7 / 6 steps (ck2–6). With a single file there was no question of which file to edit. Locating code was done by exact `src.index("def …")` anchors inside Python patch scripts ([5.12], [6.7], [6.8]).

**Search.** c1 did almost no search of its own code. It searched the SDE with `bzcat | grep` [2.3–2.4] and in-process SDE queries ([1.6], [5.7], [6.5–6.6]). At ck2 it brute-forced the formula order and rounding against the spec tables [2.5–2.6].

**Implementation.** Single file throughout; SLOC went from 286 to 927 (data.json). Most edits were `str.replace` patch scripts run through `python -` ([2.7], [3.4], [4.4], [4.5], [5.10–5.12], [5.15], [6.7], [6.8]). The Edit tool was used only twice [5.8–5.9]. Two mid-course refactors were done inside the file. At ck4 it factored out invention-source selection for reuse by `plan` [4.4]. At ck6 it split `invention_plan` into setup and plan, and rewrote `build_plan` as a ledger [6.7–6.8].

**Verification.** c1 diffed the spec examples verbatim at every checkpoint ([2.8], [4.5], [5.12], [5.15]). It ran SDE-wide sweeps over 1,092 inventables [2.9] and checked build-order consistency [5.17–5.18]. At ck6 it had kept no copy of the old code. It recovered a baseline by loading the stale `__pycache__` bytecode and compared old and new outputs for 5 build strings [6.10–6.11].

**Struggles.**
- At ck2 the sweep raised `No relics found for 'Confessor'/'Hecate'/'Jackdaw'/'Svipul'` [2.9]. c1 patched the code to print these with the Tech II layout [2.10], and its summary says they are "invented from Tech I blueprints rather than relics". The real cause is in `relic_quality`, which uses `name.startswith(prefix)` (`checkpoint_6/snapshot/industry.py:375-379`), so "Small Intact Hull Section" never matches. The build-string parser reuses the same function (line 702), which is why ck4 `svipul_l1` fails ("No published item named 'Svipul 1 Accelerant Decryptor Small Malfunctioning Hull Section'").
- At ck3 it assumed "TE also skips [reactions]" and flagged this as a "Decision for you". The hidden test expects run time 162 for Fernite Carbide at TE 10 (`tests/cases/checkpoint_3/fernite_carbide.json`).
- At ck5 the first config validator rejected values above 30. c1 then changed it to cap at 30 [5.11] and cited `min(30, split_days)` in its summary. The hidden test expects a non-zero exit code.
- Also at ck5, Fernite Carbide (exactly 3.0 days) needed to be split [5.12]. c1 concluded "a job may run up to but not including split_days" [5.15].

## c2
**Navigation.** c2 re-read everything at every checkpoint. At ck2 it ran `cat industry.py` and then `for f in *.py; cat` [2.2–2.3]. At ck3 it cat'd 6 modules [3.2–3.3]. At ck4 it cat'd 11 files over two calls [4.2–4.3]. At ck5 and ck6 it again cat'd essentially all modules ([5.2–5.4], [6.2–6.4], [6.8]). It made its first edit after 13 / 5 / 5 / 7 / 8 steps. It never used targeted reading, so the module layout did not narrow what it read. Edits still landed in the expected module.

**Search.** It used `grep` on its own code twice ([3.5] in invention.py, which returned no output, and [6.7] for `structure_rigs`). Otherwise it explored the SDE with bzcat and Python, which was extensive at ck2 [2.4–2.13]. At ck2 it also brute-forced the probability formula order over three scripts [2.7–2.9].

**Implementation.** The ck1 package had `sde_loader`, `inventory`, `industry_data`, `recipe`, `item_info`, `report`, `models`, `constants` and `cli` [1.6–1.8].
- ck2 added `invention.py` plus edits to constants and cli [2.14–2.16].
- ck3 touched models, recipe, report and cli for one feature [3.6–3.8].
- ck4 added `plan.py` and wired it into cli [4.6–4.8].
- ck5 and ck6 were confined to `plan.py` and `cli.py` ([5.8–5.13], [6.9–6.10]).

`plan.py` grew from 287 lines [4.6] to 430 (wc at [6.2]) to 528 by the end. It holds config parsing, build-string parsing, tree expansion, splitting and CSV writing. Interpretation: planning concentrated in one module, while the earlier modules stayed small (cc_max went from 21 to 32 at ck6, data.json).

**Verification.** c2 did verbatim diffs ([2.17], [4.8], [5.10], [5.13]) and a sweep over 8,211 products [1.9]. It probed edge cases, including Rhea `--build-all` [5.14–5.16]. It took the Rhea output for a bug, then found its grep had been wrong ("False alarm") [5.16]. At ck6 it checked that output without stocks was byte-identical to before.

**Struggles.**
- **Science skills.** At ck2 it printed the blueprints that require a fourth skill [2.11], including `Capital Ship Construction`. It then chose to count only skills in the "Science" group (`eve_industry/invention.py:225`) and disclosed this in its summary. The hidden test case lists `num_science_skills: 3` for Dual Giga (`tests/cases/checkpoint_2/dual_giga.json`).
- **Clamping probe.** c2's last ck2 action was to check clamping to 100 % [2.19]. The awk pipeline produced an empty name ("No published item named ''") and the checkpoint ended with the next message. The clamp test later failed (94.21 vs 100.0).
- **TE and reactions.** At ck3 it made the same assumption as c1, that TE skips reactions, and flagged it.
- **Split rule.** It adopted the same strict-split rule [5.11–5.13]. It validated `split_days` to `(0,30]` (`plan.py:101-108`) and passed the >30 error test.

## c3
**Navigation.** The re-orientation pattern was the same as c2's: `ls` and a memory-dir probe, then cat of many modules ([2.2] all 6; [4.2–4.4] 9; [5.2–5.3] 9; [6.3–6.4] 11). It made its first edit after 14 / 3 / 5 / 6 / 7 steps. At ck5 it wrote a memory note on the split boundary [5.13]. The ck6 container did not have it [6.2].

**Search.** c3 used no Grep tool, and `grep` appears only as output of a patch [4.10]. At ck2 it did the longest SDE exploration of the three [2.3–2.14], including a scan of skill groups [2.12–2.13]. It also searched exhaustively over the order of formula factors [2.6–2.9]. Its scratch scripts read private fields (`c._types` [2.21], `ind._outputs` [1.14]). Production code did not, as far as checked (`grep` for non-`self._` private access in `industry.py`/`planner.py` found none).

**Implementation.** The ck1 secrets table (final message, ck1) includes:
> `blueprints.py` | How the activity tables link blueprints to products, materials and times, which activities count as building something, and which blueprint wins when there are several.
> `report.py` | The exact output layout: labels, number formats, rounding the run time up to whole minutes …

The extensions were added as follows:
- **ck2:** new `invention.py` and `invention_report.py`, plus an appended loader function in `sde_source.py` [2.15–2.18].
- **ck3:** blueprints, report and industry [3.4–3.5]. The waste arithmetic was placed in the CLI module (`industry.py:49-50`, shown in [4.10]).
- **ck4:** new `build_string.py`, `planner.py` and `plan_report.py`, plus "hooks" into `blueprints.py` and `invention.py` [4.6–4.9].
- **ck5 and ck6:** mostly `planner.py`, plus the new `stock_list.py` [6.9]. Config validation and component defaults stayed in `industry.py` (`_component_defaults`, line 112).

Every module kept a "Secret:" docstring through ck6 (e.g. [4.7], [4.8], [6.9]). Interpretation: the decomposition persisted. Planning concentrated in `planner.py`, and the CLI took on some domain logic (waste, config).

**Verification.** c3 ran a sweep over 4,104 blueprints [1.14] and 2,184 inventables [2.21], and did verbatim diffs ([2.20], [5.8], [5.12] "ALL MATCH"). At ck4 it caught its own wrong relic name in a probe [4.12–4.13]. At ck5 it found a self-consuming recipe cycle in its sweep [5.9] and fixed it [5.10–5.11]. At ck6 it confirmed output was unchanged without stocks or targets [6.10].

**Struggles.**
- **Science skills.** It made the same Science-group restriction as c2 (`invention.py:152-153`) and stated it explicitly: "`Capital Ship Construction` (a Production skill) is listed under Skills but doesn't raise the chance."
- **Waste and TE at ck3.** It defined waste as "the amount at ME 0 minus the amount at the chosen ME". For Naga at ME 5 this gives the same 1300 as the spec's reading (ME vs ME 10), so its example check could not tell the two apart. `test_me10_with_display_waste` fails ("Expected waste=0 for Isogen at ME=10"), as do the Ark and Proteus ME5 waste tests. In the same checkpoint it applied TE to reactions and flagged this, and it passed te10.
- **split_days.** At ck5 it capped values above 30 (`planner.py:62-63`) and used the same strict-boundary rule as the others.

## Cross-condition comparison
| Question | c1 | c2 | c3 |
|---|---|---|---|
| Navigation | Whole-file cat/Read each ck; first edit after 3–7 steps | cat of ~all modules each ck; 5–13 steps | cat of ~all modules each ck; 3–14 steps |
| Search | bzcat/grep on SDE, in-process queries; no code grep | Same, plus 2 code greps | Same; private fields used in scratch scripts only |
| Implementation | 1 file, str.replace patches, internal refactors at ck4 and ck6 | 11-module package; `plan.py` absorbs ck4–6 | 12 modules with stated secrets; `planner.py` absorbs ck4–6; CLI holds waste and config logic |
| Verification | Verbatim diffs, SDE sweeps, pycache baseline at ck6 | Verbatim diffs, sweeps, edge probes; clamp probe broke | Verbatim diffs, sweeps, cycle check; caught own probe errors |
| Struggles | Relic-prefix heuristic; TE skips reactions; caps split_days | Science-group skills; TE skips reactions | Science-group skills; waste baseline ME0; caps split_days |
| Shared | Strict split boundary; Nitrogen 34-vs-35 flagged in ck6 | Same | Same |

All three cells used the same workflow: read everything, explore the SDE, patch, diff against the spec examples, sweep, and summarise with flagged decisions. Two decisions coincide across all three: the strict-split inference ([5.15] c1, [5.13] c2, ck5 summary c3) and the Nitrogen Fuel Block "34 is an error in the example" judgement at ck6. The differences are in individual interpretations, not in workflow.
- c2 and c3 both did more SDE exploration at ck2, and both arrived at the Science-group reading. c1 counted every non-encryption skill (`industry.py:387-388, 482`).
- For the ck3 ambiguities, c1 and c2 made the same choice and c3 made the other.

Nothing in the traces shows an agent citing the modular or Parnas instruction when it made any of these choices. The extra ck2 exploration in c2 and c3 cannot be attributed to the prompt from one seed.

## Failures traced to behaviour
| Root cause | Kind | c1 | c2 | c3 |
|---|---|---|---|---|
| Relic `startswith` misses "Small … Hull Section" (Jackdaw ck2; Svipul build string ck4) | Data heuristic; self-found anomaly rationalised [2.9–2.10] | 5+3 | – | – |
| Only Science-group skills counted (dual_giga ×2, clamp) | Spec reading ("science skill"), disclosed | – | 15 | 15 |
| TE not applied to reactions (fernite te10) | Spec ambiguity, disclosed | 4 | 4 | – |
| Waste = ME0 − ME (me10_waste, ark, proteus) | Spec reading; example could not tell the readings apart | – | – | 12 |
| Strict `< split_days` boundary (kronos_invent, loki_l1_1d, revelation_10_3d; ck6 kronos) | Generalised from one example, not from the spec's formula (`checkpoint_5.md` l.25ff) | 7 | 7 | 7 |
| split_days > 30 capped, not rejected | Spec contradiction (`<= 30` vs `min(30,…)`) | 2 | – | 2 |
| ion_siege_real datacore `end_amount` (1006 vs 0); c1/c2 also list Crystallite Alloy | Stock handling for invention inputs; never discussed in traces | 1 | 1 | 1 |
| **Total** | | **22** | **27** | **37** |

Notes:
- **Split boundary.** The hidden diffs are identical in all three cells (e.g. expected `Photonic Metamaterials 299/300 runs` vs actual `262 ×8`, in each cell's `checkpoint_5/evaluation/stdout.txt`). The reference keeps a 30.0-day job when splitting, but splits a single job that lands exactly at the limit (`solutions/checkpoint_5/plan_service.py:115-131`). That asymmetric rule is what the spec's pseudocode encodes, and no agent implemented the pseudocode literally.
- **Never attempted.** No failure belongs to this category. Every failing behaviour was implemented and at least partially self-checked.

## Caveats
- One seed per cell, so the counts reflect individual choices, not effects. A single ck2 decision is worth 15 instances through regression re-counting, which dominates the 22/27/37 ranking.
- Digest lines are truncated. Patch contents were inferred from snapshots and from greps of raw `stdout.jsonl` and `evaluation/stdout.txt`.
- I read the reference solution only to explain the split-boundary failures. The agents never saw it.
- Steps-before-first-edit counts include memory-dir probes and SDE exploration, so they are not pure code-navigation cost.
