"""Writers for the different kinds of user-facing output."""

import os
import platform
import select
import stat
import sys
import time

RESET = "\033[0m"
COLORS = {
    "Error": "\033[1;31m",    # red
    "Warning": "\033[1;33m",  # yellow
    "Success": "\033[1;32m",  # green
    "Debug": "\033[1;34m",    # blue
}
BOX_COLOR = "\033[1;37;41m"   # white on red

# How long to wait for piped STDIN data that has not arrived yet.
STDIN_WAIT = 1.0

_TRUE = ("1", "true", "yes", "on", "always")
_FALSE = ("0", "false", "no", "off", "never")


def parse_color(value):
    """Normalise a ``color`` setting to ``True``, ``False`` or ``"auto"``."""
    if isinstance(value, bool):
        return value
    text = "" if value is None else str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return "auto"


def _isatty(stream):
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _stdin_ready(stream, timeout):
    """True when reading ``stream`` will not block indefinitely."""
    try:
        fd = stream.fileno()
        mode = os.fstat(fd).st_mode
    except (AttributeError, ValueError, OSError):
        return True  # in-memory stream
    if stat.S_ISREG(mode) or stat.S_ISCHR(mode):
        return True
    try:
        ready, _, _ = select.select([fd], [], [], timeout)
    except (OSError, ValueError):
        return True
    return bool(ready)


class Output:
    """Routes messages to STDOUT/STDERR and the log file.

    Honours ``--quiet``, ``--debug[=<group>]`` and ``--[no-]color``.
    """

    def __init__(self, quiet=False, debug=False, stdout=None, stderr=None, stdin=None,
                 color="auto", logger=None, start_time=None):
        self.quiet = quiet
        if debug == "":
            debug = True
        self.debug_enabled = bool(debug)
        self.debug_group = debug if isinstance(debug, str) else None
        self._stdout = stdout
        self._stderr = stderr
        self._stdin = stdin
        self._color = parse_color(color)
        self.logger = logger
        self.start_time = time.monotonic() if start_time is None else start_time

    @property
    def stdout(self):
        return self._stdout or sys.stdout

    @property
    def stderr(self):
        return self._stderr or sys.stderr

    @property
    def stdin(self):
        return self._stdin or sys.stdin

    # -- colors -----------------------------------------------------------

    def set_color(self, value):
        self._color = parse_color(value)

    @property
    def color(self):
        """Whether output is colorized (auto: STDOUT is a TTY, not Windows)."""
        if self._color == "auto":
            return _isatty(self.stdout) and platform.system() != "Windows"
        return self._color

    def _label(self, kind, label=None):
        label = label or f"{kind}:"
        return f"{COLORS[kind]}{label}{RESET}" if self.color else label

    # -- log file -----------------------------------------------------------

    def _log_file(self, text):
        if self.logger is not None:
            self.logger.write(text)

    def elapsed(self):
        return time.monotonic() - self.start_time

    # -- message categories ---------------------------------------------------

    def line(self, text=""):
        """Print a line on STDOUT unconditionally."""
        print(text, file=self.stdout)

    def log(self, text, sensitive=False):
        """Informational line on STDOUT unless --quiet; logged unless sensitive."""
        if not self.quiet:
            print(text, file=self.stdout)
        if not sensitive:
            self._log_file(text)

    def success(self, text):
        if not self.quiet:
            print(f"{self._label('Success')} {text}", file=self.stdout)

    def warning(self, text):
        if not self.quiet:
            print(f"{self._label('Warning')} {text}", file=self.stderr)
        self._log_file(f"Warning: {text}")

    def error(self, text, sensitive=False):
        print(f"{self._label('Error')} {text}", file=self.stderr)
        if not sensitive:
            self._log_file(f"Error: {text}")

    def error_multi_line(self, lines, sensitive=False):
        """Show an error in a highlighted box on STDERR."""
        lines = [str(line).replace("\t", "    ") for line in lines] or [""]
        lines = ["Error: " + lines[0]] + ["       " + line for line in lines[1:]]
        width = max(len(line) for line in lines)
        border = "+" + "-" * (width + 2) + "+"
        box = [border] + [f"| {line.ljust(width)} |" for line in lines] + [border]
        if self.color:
            box = [f"{BOX_COLOR}{row}{RESET}" for row in box]
        print("\n".join(box), file=self.stderr)
        if not sensitive:
            self._log_file("\n".join(lines))

    def debug(self, text, group=None):
        """Debug line with elapsed time; ``--debug=<group>`` filters by group."""
        if not self.debug_enabled:
            return
        if self.debug_group is not None and group != self.debug_group:
            return
        label = f"Debug ({group}):" if group else "Debug:"
        message = f"{text} ({self.elapsed():.3f}s)"
        print(f"{self._label('Debug', label)} {message}", file=self.stderr)
        self._log_file(f"{label} {message}")

    # -- user input -------------------------------------------------------------

    def prompt(self, question):
        """Show ``question``, read one line and return it trimmed and lowercased."""
        self.stdout.write(question)
        self.stdout.flush()
        try:
            answer = self.stdin.readline()
        except (AttributeError, OSError, ValueError):
            answer = ""
        return (answer or "").strip().lower()

    def confirm(self, question, assoc=None):
        """Ask ``question [y/n]``; ``--yes`` auto-confirms. Return True to proceed."""
        if assoc and assoc.get("yes"):
            return True
        if self.prompt(f"{question} [y/n] ") != "y":
            self.warning("Operation cancelled.")
            return False
        return True

    def read_stdin(self, timeout=STDIN_WAIT):
        """Return all piped STDIN content, or ``None`` if there is none."""
        stream = self.stdin
        if stream is None or _isatty(stream) or not _stdin_ready(stream, timeout):
            return None
        try:
            data = stream.read()
        except (OSError, ValueError):
            return None
        return data or None
