"""Writers for the different kinds of user-facing output."""

import sys


class Output:
    """Routes messages to STDOUT/STDERR, honouring --quiet and --debug."""

    def __init__(self, quiet=False, debug=False, stdout=None, stderr=None):
        self.quiet = quiet
        self.debug_enabled = debug
        self._stdout = stdout
        self._stderr = stderr

    @property
    def stdout(self):
        return self._stdout or sys.stdout

    @property
    def stderr(self):
        return self._stderr or sys.stderr

    def line(self, text=""):
        """Print a line on STDOUT unconditionally."""
        print(text, file=self.stdout)

    def log(self, text):
        """Print an informational line on STDOUT unless --quiet."""
        if not self.quiet:
            print(text, file=self.stdout)

    def success(self, text):
        if not self.quiet:
            print(f"Success: {text}", file=self.stdout)

    def warning(self, text):
        if not self.quiet:
            print(f"Warning: {text}", file=self.stderr)

    def error(self, text):
        print(f"Error: {text}", file=self.stderr)

    def debug(self, text):
        if self.debug_enabled:
            print(f"Debug: {text}", file=self.stderr)
