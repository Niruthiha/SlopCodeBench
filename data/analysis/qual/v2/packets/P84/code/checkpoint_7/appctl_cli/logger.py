"""Append-only file log of every invocation at ``<root>/logs/appctl.log``."""

import os
import re
import shlex
from datetime import datetime, timezone

from . import PROGRAM_NAME

LOG_DIR = "logs"
LOG_FILE = f"{PROGRAM_NAME}.log"
DELIMITER = "-" * 72
REDACTED = "[REDACTED]"

# ``--key=value`` arguments whose value must never reach the disk.
SENSITIVE_KEY_RE = re.compile(r"pass|pwd|secret|token|api[-_]?key|private[-_]?key|auth|credential",
                              re.IGNORECASE)


def log_path(root_dir):
    return os.path.join(root_dir, LOG_DIR, LOG_FILE)


def utc_timestamp(now=None):
    """ISO 8601 UTC timestamp with second precision, e.g. ``2024-01-31T12:00:00Z``."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def redact_argv(argv):
    """Replace the values of sensitive ``--key=value`` arguments."""
    redacted = []
    for index, token in enumerate(argv):
        if token == "--":
            redacted.extend(argv[index:])
            break
        if token.startswith("--") and "=" in token:
            key = token[2:].split("=", 1)[0]
            if SENSITIVE_KEY_RE.search(key):
                token = f"--{key}={REDACTED}"
        redacted.append(token)
    return redacted


class FileLogger:
    """Writes timestamped entries; write failures silently disable logging."""

    def __init__(self, path, enabled=True):
        self.path = path
        self.enabled = bool(enabled and path)

    def start_invocation(self, argv):
        """Write the delimiter line and the (redacted) command line."""
        command = shlex.join([PROGRAM_NAME] + redact_argv(list(argv)))
        self._append(f"{DELIMITER}\n[{utc_timestamp()}] Command: {command}\n")

    def write(self, text):
        """Append one entry; every line of it carries the timestamp."""
        stamp = utc_timestamp()
        self._append("".join(f"[{stamp}] {line}\n" for line in str(text).split("\n")))

    def _append(self, data):
        if not self.enabled:
            return
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(data)
        except OSError:
            self.enabled = False
