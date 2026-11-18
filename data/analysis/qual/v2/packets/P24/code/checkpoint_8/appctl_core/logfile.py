"""Invocation log file.

Secret: where the log file lives, the timestamp format of each entry, the
delimiter line written at the start of every invocation, and that write
failures never interrupt the command.
"""

import os
from datetime import datetime, timezone

_RELATIVE_PATH = os.path.join("logs", "appctl.log")
_TIMESTAMP = "%Y-%m-%dT%H:%M:%SZ"
_DELIMITER = "========== appctl invocation (pid {pid}) =========="


def log_path(root_dir):
    return os.path.join(root_dir, _RELATIVE_PATH)


def timestamp(now=None):
    """UTC timestamp in ISO 8601 form, e.g. ``2026-01-02T03:04:05Z``."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).strftime(_TIMESTAMP)


class LogFile:
    """Appends timestamped entries to the log file (or does nothing when
    disabled)."""

    def __init__(self, path, enabled=True):
        self.path = path
        self.enabled = bool(enabled and path)

    def _append(self, lines):
        if not self.enabled:
            return
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write("".join(line + "\n" for line in lines))
        except OSError:
            pass

    def start_invocation(self):
        self.write(_DELIMITER.format(pid=os.getpid()))

    def write(self, text):
        """Append ``text``; every line carries the same timestamp."""
        stamp = timestamp()
        self._append(f"[{stamp}] {line}" for line in str(text).split("\n"))


class NullLog(LogFile):
    def __init__(self):
        super().__init__(None, enabled=False)
