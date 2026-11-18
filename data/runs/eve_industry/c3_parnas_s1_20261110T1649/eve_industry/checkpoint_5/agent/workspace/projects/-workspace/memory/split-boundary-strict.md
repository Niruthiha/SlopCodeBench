---
name: split-boundary-strict
description: EVE planner job splitting — jobs must finish strictly under split_days (spec text says ">" but examples require it)
metadata:
  type: project
---
In the EVE industry planner (`/workspace/planner.py`), the `--build-all` job split uses max_runs = ceil(limit/days_per_run) - 1, not floor(...).

**Why:** The spec says "split if > split_days", but its example splits a 30-run Fernite Carbide reaction that lasts exactly 3.0 days (10800s * 0.8 te_bonus) with split_days 3. Floating point does not explain this, since 3/0.1 == 30.0 exactly. Only the "strictly under the limit" reading matches all of the examples.

**How to apply:** Keep this interpretation if later stages change splitting. Splitting only happens in build-all mode (the root job is split too). Without the flag the output is unchanged from the previous stage.
