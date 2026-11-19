# SlopCodeBench design-prompt pilot: harness, data and how to rerun

This repo holds everything from pilot 1 ("What would Parnas do?") on [SlopCodeBench](https://github.com/SprocketLab/slop-code-bench). The pilot's background and measures are in `PILOT_README.md`.

## What's here

| Path | What it is |
|---|---|
| `harness/patches/` | 6 commits on top of upstream SlopCodeBench `af5a9cb` (`UPSTREAM_BASE_COMMIT`): Claude Code agent config, isolation and reset patches, the Opus 5.5 model config, and the prompts. Patch 0006 adds the rerun's `*_every` prompts |
| `prompts/` | the 4 pilot-1 condition prompts (c1 default, c2 modular, c3 Parnas, c4 performance) and the 3 rerun prompts `c2_modular_every`, `c3_parnas_every`, `c4_performance_every` (same design line at every checkpoint) |
| `scripts/` | `run_cell.sh` (one problem × condition × seed), `pilot.sh`, `rerun_every.sh` (rerun batch), `resume_cell.sh`, `verify_setup.sh` (pre-run isolation checks), `check_cell.py` (post-run isolation check), `failure_summary.py`, `trace_summary.py` (per-checkpoint time, cost, tokens, tool calls), `net_up.sh` (egress), `refcheck*.sh` (reference-solution check), `instruments/` |
| `data/runs/<problem>/<cond>_s1_<ts>/` | full run output for the 4 problems: per-checkpoint agent traces, `checkpoint_results.jsonl`, `result.json`, logs |
| `data/runs/scores_adjusted.json`, `ALWAYS_FAIL.md` | scores with the benchmark-defect tests removed (see `BENCHMARK_DEFECTS.md`) |
| `data/analysis/` | comparison and qualitative analysis |

The runs cover 4 problems: `sith`, `eve_industry`, `recli`, `metric_transform_lang`. One seed per run, Opus 5.5, thinking=high. The `metric_transform_lang` runs use the **old** prompt, which still had the DESIGN.md planning line (`c1_planning`; see `OLD_PROMPT_RUNS.md`). The account email in the traces is replaced with `<redacted-email>`.

## Setup

1. Clone upstream and apply the patches:
   ```bash
   git clone https://github.com/SprocketLab/slop-code-bench && cd slop-code-bench
   git checkout af5a9cb && git am ../harness/patches/*.patch
   uv sync
   ```
2. Clone the problems: `git clone https://github.com/gabeorlanski/scb-problems` (we used commit `9cd9ca3`).
3. Put `scripts/*` next to the `slop-code-bench/` and `scb-problems/` folders. **Edit the hard-coded paths** in `run_cell.sh` and `verify_setup.sh`: `/home/niruthi/...` and `SCB_CLAUDE_CREDS`.
4. Credentials: `SCB_CLAUDE_CREDS` points to your own `~/.claude/.credentials.json`. The harness mounts it **read-only** into the agent container. Never copy it into the repo or the run directory. `run_cell.sh` unsets `ANTHROPIC_API_KEY` and the token env vars on purpose.
5. Run `scripts/verify_setup.sh` before every run. It must print no FAIL.

## Harness behaviour (patches P1–P4, P3b)

- Each checkpoint runs in a fresh agent container, given the previous checkpoint's code (`SCB_PARNAS_RESET=1`).
- Docs the agent wrote are deleted between checkpoints.
- MCP is isolated: `--strict-mcp-config` with an empty config.
- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` keeps the skill list identical at every checkpoint.
- The evaluation environment is separate from the agent's. Hidden tests never enter the agent container.

## The new experiment: same instruction at every checkpoint

In pilot 1 the design instruction is given **at checkpoint 1 only**: it sits in the `{% if not is_continuation %}` block. For the rerun, every checkpoint must get the same instruction.

**What to change** in each `configs/prompts/parnas/c2_modular.jinja`, `c3_parnas.jinja` and `c4_performance.jinja` (c1 has no instruction):

Move the instruction line **out** of the `if` block so it is printed on every checkpoint:

```jinja
Implement a program that 100% solves the specification. That is all you need to do.
{% if not is_continuation -%}
Use a virtual environment and ensure that a `requirements.txt` is present with any dependencies you need to solve the problem.
{% else -%}
Keep using the same virtual environment you started with, update `requirements.txt` with any new dependencies you need.
{% endif -%}
<INSTRUCTION LINE HERE: identical text, every checkpoint>

Your task is:
{{ spec.strip() }}
```

Then:

1. **Use new file names** (e.g. `c3_parnas_every.jinja`) so the pilot-1 prompts stay unchanged, and commit them so the run records the harness commit.
2. **Keep everything else fixed.** Same 4 problems, same model (`anthropic/opus-5.5`, thinking=high), and the same agent and environment configs.
3. **Run one cell at a time,** detached:
   ```bash
   setsid nohup ./run_cell.sh sith c3_parnas_every 1 > runs/logs/<name>.log 2>&1 < /dev/null &
   ```
4. **After each cell,** run `python3 check_cell.py <run_dir>` (isolation check) and `failure_summary.py`.
5. **Score against the same adjusted test set** (`BENCHMARK_DEFECTS.md`), so the results are comparable with pilot 1.

## Known issues

- `meshctl` was dropped because of a benchmark defect (`BENCHMARK_DEFECTS.md`).
- A few tests always fail even on the reference solution (`ALWAYS_FAIL.md`). Report scores both raw and adjusted.
