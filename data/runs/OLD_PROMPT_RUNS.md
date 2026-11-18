# Old-prompt runs (before 2026-11-09 ~23:40)
Every run under runs/file_backup/, runs/metric_transform_lang/, runs/gate/ used prompts that told the agent at checkpoint 1:
"Before coding, write a brief design plan in `DESIGN.md`, then implement." (all four conditions; c1 was named c1_planning).
That line was removed (harness commit in prompts/parnas/; c1 → c1_default = just-solve.jinja). These runs are a setup test
and must NOT be pooled with new-prompt runs.
