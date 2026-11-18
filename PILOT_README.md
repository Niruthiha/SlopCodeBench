# "What Would Parnas Do?" — Pilot 1 on SlopCodeBench

## What this experiment is for
**Question:** if a coding agent is told to design its program in a certain way, are *later* feature changes cheaper, more local and more correct?

**Background:**
- In the mini-CRP pilot, the "modular" version cost more and changed more existing code. The 4 Nov meeting concluded:
  - don't ask for "not modular";
  - compare explicit design goals (information hiding, "what would Parnas do") with a competing quality goal;
  - use better modularity measures than file counts;
  - measure duplication;
  - measure scatter on minimised passing changes;
  - record tokens from the harness (cached vs uncached).
- Modularity is relative to the task: a design is only modular for the changes it anticipated.

**Why SlopCodeBench:**
- It is an existing, published benchmark: 36 Python problems, each a sequence of checkpoints.
- Each checkpoint adds features through a natural-language spec, with hidden tests plus regression tests.
- The programs grow to 2,000–6,000 lines, so the tasks are harder than mini-CRP.

**What the pilot is for:** not a result. It checks that:
1. the runs work end to end;
2. the four designs actually differ;
3. the measures can be computed;
4. we get variance and cost estimates to size the main study.

## The four conditions
All conditions use the benchmark's default prompt ("just-solve"). Only checkpoint 1 gets the condition's design instruction (none for c1). Changed 2026-11-09: the planning line ("Before coding, write a brief design plan in `DESIGN.md`, then implement.") was removed from all conditions, and c1 renamed c1_planning → c1_default; runs before this change are old-prompt runs (runs/OLD_PROMPT_RUNS.md). Checkpoints 2..N get **identical, neutral** prompts in every condition, so later differences come from the design, not the instruction.

| # | Condition | Why it is here | Extra instruction (checkpoint 1 only) | File |
|---|---|---|---|---|
| 1 | Default (benchmark prompt) | Control: exactly SlopCodeBench's own just-solve prompt, comparable with the paper. | (none) | `prompts/c1_default.jinja` |
| 2 | Generic modularity | What the mini-CRP "modular" version did: vague modularity advice. | "Write the program in a modular way: split it into well-organised modules with clear, single responsibilities." | `prompts/c2_modular.jinja` |
| 3 | Parnas (information hiding) | The theory-grounded design goal (Parnas 1972): modules built around decisions likely to change. | "Decompose by information hiding. First list the design decisions that are hard to make or likely to change. Give each its own module whose secret is that decision, and state the secret in one sentence. Other modules use it only through an interface that stays valid if the secret changes. Never share internal data structures across modules." | `prompts/c3_parnas.jinja` |
| 4 | Performance | The competing quality goal the supervisor suggested, used instead of "not modular". | "The most important quality of this program is runtime speed and low memory use. Optimise for that." | `prompts/c4_performance.jinja` |

**Not in pilot 1:** hints about future changes. They give the agent advance knowledge, so they belong to a later experiment, run only if Parnas shows an effect.

## Expectations (hypotheses for the main study, not tested by the pilot)
- **H1:** Parnas makes later changes cheaper and more local than the planning baseline, mainly for changes that vary a decision the agent hid (e.g. a new input format).
- **H2:** Generic modularity is no better than baseline; it may be worse, as in mini-CRP.
- **H3:** Performance is the worst for later changes.

## What we measure
**After checkpoint 1 (did the design actually differ?):**
- **Decision localisation:** for each design decision (e.g. input format, storage, output format), how many modules contain code for it. Lower is better hiding.
- **Data leakage:** modules reaching into another module's internal data (dict keys, tuple positions, attributes).
- **Propagation cost and dependency cycles:** computed with SlopCodeBench's own metrics.
- **Design notes (if the agent writes any; no longer requested):** did a Parnas agent list decisions and secrets, and does the code follow them?
- **Size:** lines, files, functions (description only, not a modularity measure).

**At each later checkpoint (did the design help?):**
- **Correctness:** new tests passed; regression tests passed; the first checkpoint that fails.
- **Cost:** tokens from the harness logs: input (uncached), cache read, cache write, output, turns, time. Reading and editing are reported separately.
- **Scatter:** files and functions changed. Share of changes that *modify existing code* outside the module that owns the decision.
- **Minimised scatter:** shrink the passing change to the smallest version that still passes, then measure its scatter. Done on a subset of steps.
- **Duplication:** code copied instead of reusing or changing existing functions.
- **Exposure:** how much of other modules' code the agent read before editing.
- **Erosion:** SlopCodeBench's quality metrics over the checkpoints.

## Pilot setup
- **Problems:** 2, not reused in the main study. Suggested: `file_backup` and `dynamic_config_service_api` (multi-file, moderate size).
- **Runs:** 2 problems × 4 conditions × 2 repeats = **16 runs**, each through all checkpoints.
- **Hold everything else fixed:**
  - same model;
  - same Claude Code version (`version=2.0.51` or one pinned version);
  - same thinking setting;
  - same environment config.

**Example command (one condition):**
```bash
uv run slop-code run \
  --agent claude_code \
  --model anthropic/<pinned-model> \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --prompt /path/to/parnas-pilot/prompts/c3_parnas.jinja \
  --problem file_backup --problem dynamic_config_service_api \
  thinking=low version=2.0.51
```
Repeat for c1, c2 and c4, then run everything a second time.

## Before running: checks
1. **Block internet** except the model API, and disallow web tools. The problems and solutions are on GitHub.
2. **Hidden tests:** confirm no `.evaluation_tests` folder exists in the workspace before each checkpoint. If the agent creates one, it can replace the hidden tests.
3. **Isolation:** the harness runs Claude Code with permission checks off inside its container, so run it only in an isolated container.
4. **Same limits** (turns, cost, time) for every condition; log any run that hits a limit.
5. **Keep everything:** transcripts (stream-json), the workspace after each checkpoint, any agent-written notes, and test results.

## Which question (decided): does code built with a design goal make later changes easier for a *fresh* agent?
- The design instruction reaches **only checkpoint 1**.
- Before every later checkpoint, the harness deletes `DESIGN.md`, `CLAUDE.md`, `AGENTS.md` and `.claude/` from the code folder, and empties `~/.claude` (session history). The code itself is kept.
- This applies to every condition, the pilot included. See `harness_reset.patch.md`.
- The other question (does keeping the guidance at *every* checkpoint help?) is a separate, later experiment. It would add the instruction at every checkpoint, the same way in every condition.

## Pilot success criteria
- All 16 runs finish without infrastructure errors.
- The reset works: checkpoint 2+ sessions cannot see DESIGN.md or earlier conversations (checked from logged folder listings, not only from transcripts).
- The Parnas runs show decisions and secrets (in notes, transcript or code), and the code differs from generic modularity on decision localisation. If not, revise the instruction before the main study.
- Every measure above can be computed from the saved files.
- We have a cost per checkpoint and a spread across repeats, to choose the main study size (planned: 10–12 problems × 4 conditions × 3 repeats).
