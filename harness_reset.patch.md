# Harness change: fresh extender after checkpoint 1 (Question 2)

## What SlopCodeBench does now (checked in the source)
| Route for the instruction to reach checkpoint 2+ | Happens now? | Where |
|---|---|---|
| 1. Conversation continues | **No.** Each checkpoint is a new `claude --print` call. `--continue` is used only for a retry *within* a checkpoint. But if a later checkpoint's first call fails before it starts a session, that retry could continue checkpoint 1's conversation. | `agents/claude_code/agent.py:950-960, 864` |
| 2. Agent reads DESIGN.md | **Yes, possible.** The code folder is kept, so DESIGN.md stays. | workspace persists |
| 3. Saved history | **Yes, possible.** `~/.claude` is created once per problem run and never cleared. Checkpoint 1's full session log (instruction included) stays readable in `~/.claude/projects/`. | `agent.py:403-416`; `runner.py:645-662` (`reset()` clears only in-memory state) |
| Auto-loaded instructions | Only if a `CLAUDE.md` (or `.claude/` settings) exists in the repo. None are created by us; the agent could create one. | — |

## Policy (all conditions, pilot included)
Before every checkpoint after the first:
1. Delete from the workspace: `DESIGN.md`, `CLAUDE.md`, `AGENTS.md`, `.claude/`. Keep all code.
2. Empty `~/.claude` (the agent's mounted `claude_home`), keeping only `settings.json`. The previous checkpoint's traces are saved *before* this point (`save_agent_checkpoint_info` runs after each checkpoint), so no data is lost.

## Code (in `src/slop_code/agent_runner/runner.py`, `_setup_for_checkpoint`)
```python
import shutil  # at top of file

    def _setup_for_checkpoint(self, checkpoint: CheckpointConfig) -> None:
        if self.metrics_tracker.state in {
            AgentStateEnum.INITIALIZED,
            AgentStateEnum.PENDING,
        }:
            self.agent.setup(session=self.session)
            return

        self.agent.finish_checkpoint(reset_context=True)

        # --- Parnas experiment: fresh extender (Question 2) ---
        ws = self.session.working_dir
        for name in ("DESIGN.md", "CLAUDE.md", "AGENTS.md"):
            p = ws / name
            if p.exists():
                p.unlink()
        if (ws / ".claude").exists():
            shutil.rmtree(ws / ".claude")
        home = getattr(self.agent, "_trace_dir", None)  # claude_home
        if home is not None and home.exists():
            for p in home.iterdir():
                if p.name != "settings.json":
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
        logger.info("parnas.reset_done", checkpoint=checkpoint.name)
```

## Verify in the pilot (before trusting any result)
- After checkpoint 1, the snapshot contains DESIGN.md. At the start of checkpoint 2, the workspace and `~/.claude` don't contain it. Log a listing of both.
- The checkpoint-2+ prompt text is identical across conditions (already true for our templates).
- Grep the checkpoint-2+ transcripts for `DESIGN`, `secret`, `information hiding`, `Parnas`, `.claude/projects`. Expect zero hits from files. Hits in code comments are fine, because the code is the treatment.
- Note: files written inside the container may be owned by root. If deleting from the host fails, run the deletion inside the container instead. Untested.
