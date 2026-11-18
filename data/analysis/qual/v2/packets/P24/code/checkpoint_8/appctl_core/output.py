"""Output streams.

Secret: which stream each kind of output goes to, the prefix it carries and
its color, which kinds are copied to the log file, how quiet and debug modes
affect it, and how questions are asked and answered on STDIN.
"""

import os
import select
import stat
import sys
import time

from . import messages as _messages
from .logfile import NullLog

_RESET = "\x1b[0m"
_PREFIX_COLORS = {
    "Error": "\x1b[1;31m",    # bold red
    "Warning": "\x1b[1;33m",  # bold yellow
    "Success": "\x1b[1;32m",  # bold green
    "Debug": "\x1b[1;34m",    # bold blue
}
_BOX_COLOR = "\x1b[1;37;41m"  # bold white on red
_STDIN_WAIT = 1.0
_TRUE = {"true", "yes", "on", "1", "always", "force"}
_FALSE = {"false", "no", "off", "0", "never", "none"}


def _isatty(stream):
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def color_enabled(setting, stream, os_name=None):
    """Decide whether to colorize: ``setting`` is True, False or ``"auto"``."""
    if isinstance(setting, bool):
        return setting
    text = str(setting).strip().lower() if setting is not None else "auto"
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return _isatty(stream) and (os_name or os.name) != "nt"


def _pipe_has_data(stream):
    """False when ``stream`` is a pipe/socket that stays silent for a while."""
    try:
        fd = stream.fileno()
        mode = os.fstat(fd).st_mode
    except (AttributeError, OSError, ValueError):
        return True
    if not (stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode)):
        return True
    try:
        ready, _, _ = select.select([fd], [], [], _STDIN_WAIT)
    except (OSError, ValueError):
        return True
    return bool(ready)


class Output:
    def __init__(self, stdout, stderr, quiet=False, debug=False, *, stdin=None,
                 color=False, log=None, start=None):
        self._stdout = stdout
        self._stderr = stderr
        self._stdin = stdin
        self._quiet = bool(quiet)
        self._debug = debug
        self._color = bool(color)
        self._log = log or NullLog()
        self._start = time.monotonic() if start is None else start
        self._stdin_data = None
        self._stdin_read = False

    def configure(self, quiet=None, debug=None, color=None):
        if quiet is not None:
            self._quiet = bool(quiet)
        if debug is not None:
            self._debug = debug
        if color is not None:
            self._color = bool(color)

    def disable_log(self):
        """Stop writing to the log file (e.g. once it has been removed)."""
        self._log = NullLog()

    @property
    def color(self):
        return self._color

    @property
    def stdout(self):
        return self._stdout

    @property
    def stderr(self):
        return self._stderr

    # --- writing ----------------------------------------------------------

    def _write(self, stream, text):
        stream.write(text if text.endswith("\n") else text + "\n")

    def _prefix(self, label):
        text = f"{label}:"
        if self._color:
            return f"{_PREFIX_COLORS[label.split()[0]]}{text}{_RESET}"
        return text

    def line(self, text=""):
        """Command result data; always shown, never logged."""
        self._write(self._stdout, text)

    def write_stderr(self, text):
        """Raw text for STDERR (e.g. relayed from a child process)."""
        self._write(self._stderr, text)

    def usage(self, text):
        """Help and usage text; always shown."""
        self._write(self._stdout, text)

    def log(self, text, sensitive=False):
        """Informational message: STDOUT and the log file, unless quiet.

        Sensitive messages are shown but never written to the log file.
        """
        if self._quiet:
            return
        self._write(self._stdout, text)
        if not sensitive:
            self._log.write(text)

    info = log

    def log_only(self, text):
        """A note that goes to the log file only."""
        self._log.write(text)

    def success(self, text):
        if not self._quiet:
            self._write(self._stdout, f"{self._prefix('Success')} {text}")

    def warning(self, text):
        self._write(self._stderr, f"{self._prefix('Warning')} {text}")
        self._log.write(f"Warning: {text}")

    def error(self, text, sensitive=False, log_text=None):
        """Report an error on STDERR; log it unless it is sensitive (in which
        case only ``log_text``, a redacted form, is logged if given)."""
        self._write(self._stderr, f"{self._prefix('Error')} {text}")
        if not sensitive:
            self._log.write(f"Error: {text}")
        elif log_text:
            self._log.write(f"Error: {log_text}")

    def error_multi_line(self, lines, sensitive=False, log_text=None):
        """Report a multi-line error inside a highlighted box on STDERR."""
        lines = [str(l) for l in lines] or [""]
        lines[0] = f"Error: {lines[0]}"
        width = max(len(l) for l in lines)
        border = "+" + "-" * (width + 2) + "+"
        body = [border] + [f"| {l.ljust(width)} |" for l in lines] + [border]
        if self._color:
            body = [f"{_BOX_COLOR}{row}{_RESET}" for row in body]
        self._write(self._stderr, "\n".join(body))
        if not sensitive:
            self._log.write("\n".join(lines))
        elif log_text:
            self._log.write(f"Error: {log_text}")

    def report(self, exc):
        """Report a ``CliError``."""
        if exc.lines is not None:
            self.error_multi_line(exc.lines, exc.sensitive, exc.log_message)
        else:
            self.error(exc.message, exc.sensitive, exc.log_message)

    def debug(self, text, group=None):
        """Debug message, shown when debug mode is on. With ``--debug=<group>``
        only messages of that group are shown."""
        active = self._debug
        if not active:
            return
        if isinstance(active, str) and group != active:
            return
        label = f"Debug ({group})" if group else "Debug"
        elapsed = f"({time.monotonic() - self._start:.3f}s)"
        self._write(self._stderr, f"{self._prefix(label)} {text} {elapsed}")
        self._log.write(f"{label}: {text} {elapsed}")

    # --- reading ----------------------------------------------------------

    def _input(self):
        return self._stdin if self._stdin is not None else sys.stdin

    def _flush(self):
        for stream in (self._stdout, self._stderr):
            try:
                stream.flush()
            except (AttributeError, OSError, ValueError):
                pass

    def prompt(self, question):
        """Show ``question``, read one line from STDIN and return it trimmed
        and lowercased ("" when nothing could be read)."""
        self._stdout.write(question)
        self._flush()
        try:
            answer = self._input().readline()
        except (AttributeError, OSError, ValueError):
            answer = ""
        return (answer or "").strip().lower()

    def confirm(self, question, assume_yes=False):
        """Ask a ``[y/n]`` question; anything but ``y`` cancels."""
        if assume_yes:
            return True
        if self.prompt(f"{question} [y/n] ") == "y":
            return True
        self.warning(_messages.operation_cancelled())
        return False

    def read_stdin(self):
        """All of STDIN without the trailing newline, or ``None`` when STDIN
        is interactive, unavailable or empty. Read at most once."""
        if not self._stdin_read:
            self._stdin_read = True
            stream = self._input()
            data = None
            if stream is not None and not _isatty(stream) and _pipe_has_data(stream):
                try:
                    data = stream.read()
                except (AttributeError, OSError, ValueError):
                    data = None
            if isinstance(data, bytes):
                data = data.decode(errors="replace")
            data = data.rstrip("\r\n") if data else ""
            self._stdin_data = data or None
        return self._stdin_data
