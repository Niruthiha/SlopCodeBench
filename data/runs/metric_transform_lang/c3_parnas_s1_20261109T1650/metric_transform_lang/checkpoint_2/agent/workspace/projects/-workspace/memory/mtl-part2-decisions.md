---
name: mtl-part2-decisions
description: Interpretation choices made when implementing MTL Part 2 (schemas/params/calcs/lag) in /workspace
metadata:
  type: project
---
MTL Part 2 (schemas, params, calcs, lag/lead) was implemented 2026-11-09 on top of the Part 1 CLI in /workspace (mtl.py + mtl_core/). No spec or tests are kept in the repo.

Judgment calls where the spec was ambiguous:
- `--strict` is accepted but does nothing (Part 1's spec wasn't available).
- Unknown `--param` keys are ignored. An untyped param gets its type from its default literal, or is a string if it has no default.
- A calc may widen int to float when the declared type is float; any other mismatch is exit 2.
- When a schema is used, the required CSV columns are its physical fields, not the Part 1 fixed columns.
- `lag`/`lead` offset: 0 or non-literal gives exit 1, a non-int literal or param gives exit 2, and an int param <= 0 gives exit 4.
- `@stage(pre)` calcs run before all filter/apply steps, whatever their position in the body.

**Why:** if hidden tests disagree with one of these, these are the first places to look.
**How to apply:** check this list before changing error codes or calc staging.
