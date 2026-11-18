"""Multi-step operations that undo their completed steps when one step fails."""

from dataclasses import dataclass, field


@dataclass
class Step:
    id: str
    up: object
    down: object = None
    up_args: tuple = field(default_factory=tuple)
    down_args: tuple = field(default_factory=tuple)


class StepFailed(Exception):
    """A step returned ``False``."""


class RevertableStepProcessor:
    """Runs steps in order; on failure, undoes them in reverse order.

    A step fails when ``up`` raises or returns ``False``. The undo of the
    failed step runs too, so a step can clean up its own partial work.
    Undo failures are logged and the rollback continues; steps without an
    undo action are skipped silently. A processor that succeeded can still
    be rolled back later with :meth:`rollback`.
    """

    def __init__(self, output=None, name=None):
        self.output = output
        self.name = name
        self.steps = []
        self.executed = []
        self.error = None
        self.failed_step = None

    def add_step(self, step_id, up, down=None, up_args=(), down_args=()):
        self.steps.append(Step(str(step_id), up, down, tuple(up_args), tuple(down_args)))
        return self

    def _log(self, text):
        if self.output is not None:
            self.output.debug(text, group="upgrade")
            if self.output.logger is not None:
                self.output.logger.write(text)

    def _warn(self, text):
        if self.output is not None:
            self.output.warning(text)

    def execute(self):
        """Run every pending step; return whether all of them succeeded."""
        pending, self.steps = self.steps, []
        for step in pending:
            self._log(f"Executing step: {step.id}")
            self.executed.append(step)
            try:
                if step.up(*step.up_args) is False:
                    raise StepFailed(f"Step '{step.id}' failed.")
            except Exception as exc:  # any failure triggers the rollback
                self.error = exc
                self.failed_step = step
                self._log(f"Step '{step.id}' failed: {exc}")
                self.rollback()
                return False
        return True

    def rollback(self):
        """Undo the executed steps in reverse order; undo failures only warn."""
        while self.executed:
            step = self.executed.pop()
            if step.down is None:
                continue
            self._log(f"Rolling back step: {step.id}")
            try:
                if step.down(*step.down_args) is False:
                    raise StepFailed(f"Undo of step '{step.id}' failed.")
            except Exception as exc:  # keep rolling back the remaining steps
                self._warn(f"Unable to roll back step '{step.id}': {exc}")
