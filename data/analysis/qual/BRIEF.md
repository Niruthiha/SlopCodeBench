# Qualitative trace analysis — brief (one task, three conditions)

You are analysing how a coding agent (Claude Opus 5.5 in Claude Code, inside Docker) worked on ONE SlopCodeBench task under
three prompt conditions. Each cell is one run (seed 1) through N checkpoints; at each checkpoint the spec is extended and the
agent continues on its own code. Only checkpoint 1's prompt differs between conditions:
- c1 (c1_default; for metric_transform_lang it is c1_planning — read its checkpoint_1/prompt.txt): just "implement the spec".
- c2 (c2_modular): + "Write the program in a modular way: split it into well-organised modules with clear, single responsibilities."
- c3 (c3_parnas): + "Decompose by information hiding. First list the design decisions that are hard to make or likely to change. Give each its own module whose secret is that decision ... Never share internal data structures across modules."
Checkpoints 2..N get the same continuation prompt in every condition. The agent starts each checkpoint in a fresh container with no memory except its own code.

## Inputs (read-only — DO NOT modify, move or delete anything; do not run Docker or the benchmark)
Root /home/niruthi/features/scbench
- Digests (main input): analysis/qual/digests/<task>__<cond>.md. One line per tool call `[ck.step] Tool args -> result head`,
  `SAY:` lines are the agent's own text, `RESULT:` is its end-of-checkpoint summary. Step ids like [3.41] are your citations.
- Full raw traces if a digest line is truncated and you need more: <run>/<task>/checkpoint_N/agent/stdout.jsonl (large; grep, don't read whole).
- Final and per-checkpoint code: <run>/<task>/checkpoint_N/snapshot/
- Test outcomes: <run>/failure_summary.md, <run>/checkpoint_results.jsonl, <run>/<task>/checkpoint_N/evaluation.json
- Spec: scb-problems/<task>/checkpoint_N.md. Hidden tests: scb-problems/<task>/tests/ (you may read them to explain failures;
  the agent never saw them).
- Already-measured numbers (don't recompute): analysis/compare/data.json (steps, tool calls, time, tokens, cost, SLOC, files, failures).
Ignore any `_invalid_attempt/` dir and any c4_* run.

## Questions — answer per condition, then compare
1. Navigation: how did the agent re-orient at the start of each checkpoint 2..N (reading whole files, grep, listing modules, reading its own docs/README/comments, running the program)? How many steps before the first edit? Did module structure make finding the right place easier or harder?
2. Search: what did it search for and how (grep/Glob/find/reading)? Repeated reads of the same file? Lost or dead-end searches?
3. Implementation: what design did ck1 produce (files/modules, the "secrets" if c3 listed any — quote them)? How did each extension land: localized change in one module, or edits scattered across many files? Did the structure survive or erode (new god-module, duplicated logic, bypassed interfaces)? Rewrites?
4. Verification: how did it test (own scripts, examples from the spec, unit tests, ad-hoc)? Did it catch its own bugs?
5. Struggles and weaknesses: loops, repeated failing commands, misreadings of the spec, wrong assumptions, places it gave up or declared done while tests later failed. Tie each to the hidden-test failures where possible (which failures were spec misreadings vs. structural slips vs. never-attempted).
6. Differences between conditions that are clearly visible in the traces — and say explicitly where the conditions behaved the SAME. Do not force a difference. Distinguish "the prompt caused it" (only defensible if visible, e.g. the agent cites the instruction) from "it happened in this run". One seed per cell: no claims of effect.

## Rules
- Every claim cites step ids ([ck.step]) or file paths. Quote sparingly (≤2 lines).
- Facts first; label interpretation as interpretation.
- No praise words for a condition ("works", "better design"); describe what happened.
- Length: aim 1,200–2,000 words.

## Output
Write ONE file: analysis/qual/<task>.md with sections:
`## Summary` (6–10 bullets), `## c1`, `## c2`, `## c3` (each with Navigation / Search / Implementation / Verification / Struggles),
`## Cross-condition comparison` (a table with a row per question + a short paragraph), `## Failures traced to behaviour`,
`## Caveats`.
Then reply with the Summary bullets only.
