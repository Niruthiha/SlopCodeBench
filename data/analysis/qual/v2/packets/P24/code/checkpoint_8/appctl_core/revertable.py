"""Multi-step operations that undo themselves on failure.

Secret: the order in which steps run and are undone, what counts as a
failed step, and how failures of undo actions are reported.
"""

import sys

from .output import Output


class Step:
    __slots__ = ("name", "up", "down", "up_args", "down_args")

    def __init__(self, name, up, down=None, up_args=(), down_args=()):
        self.name = name
        self.up = up
        self.down = down
        self.up_args = tuple(up_args)
        self.down_args = tuple(down_args)


class StepFailed(Exception):
    """A step returned ``False`` instead of raising."""


def _reason(exc):
    return getattr(exc, "message", None) or str(exc) or type(exc).__name__


class RevertableStepProcessor:
    """Runs steps in order; when one fails, undoes every step that ran
    (including the failing one, which may have been partially applied) in
    reverse order.

    A step fails when its action raises or returns ``False``. Steps without
    an undo action are skipped silently during rollback. A failing undo
    action is logged as a warning and rollback continues with the next step.
    After a successful ``execute`` the steps can still be undone with
    ``rollback`` (e.g. because a later operation failed); rollback is
    idempotent.
    """

    def __init__(self, out=None, undo_failed=True):
        self.out = out or Output(sys.stdout, sys.stderr)
        self.undo_failed = undo_failed
        self._steps = []
        self._done = []
        self.error = None
        self.failed_step = None

    def add_step(self, name, up, down=None, up_args=(), down_args=()):
        self._steps.append(Step(name, up, down, up_args, down_args))
        return self

    @property
    def steps(self):
        return list(self._steps)

    def execute(self):
        """Run every pending step; return ``True`` on success. On failure
        roll back, keep the exception in ``error`` and return ``False``."""
        self.error = None
        self.failed_step = None
        pending, self._steps = self._steps, []
        for step in pending:
            self.out.debug(f"Executing step: {step.name}", group="revertable")
            try:
                if step.up(*step.up_args) is False:
                    raise StepFailed(f"Step '{step.name}' failed.")
            except Exception as exc:  # noqa: BLE001 - every failure triggers rollback
                self.error = exc
                self.failed_step = step.name
                self.out.debug(f"Step '{step.name}' failed: {_reason(exc)}",
                               group="revertable")
                self.out.log_only(f"Step '{step.name}' failed: {_reason(exc)}")
                if self.undo_failed:
                    self._done.append(step)
                self.rollback()
                return False
            self._done.append(step)
        return True

    def rollback(self):
        """Undo the executed steps in reverse order."""
        done, self._done = self._done, []
        for step in reversed(done):
            if step.down is None:
                continue
            self.out.debug(f"Reverting step: {step.name}", group="revertable")
            try:
                step.down(*step.down_args)
            except Exception as exc:  # noqa: BLE001 - rollback must go on
                self.out.warning(f"Unable to revert step '{step.name}': {_reason(exc)}")
