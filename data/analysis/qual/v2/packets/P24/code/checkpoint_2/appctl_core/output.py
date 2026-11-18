"""Output streams.

Secret: which stream each kind of output goes to, the prefix it carries,
and how quiet and debug modes affect it.
"""


class Output:
    def __init__(self, stdout, stderr, quiet=False, debug=False):
        self._stdout = stdout
        self._stderr = stderr
        self._quiet = quiet
        self._debug = debug

    def _write(self, stream, text):
        stream.write(text if text.endswith("\n") else text + "\n")

    def line(self, text=""):
        """Command result data; always shown."""
        self._write(self._stdout, text)

    def usage(self, text):
        """Help and usage text; always shown."""
        self._write(self._stdout, text)

    def log(self, text):
        if not self._quiet:
            self._write(self._stdout, text)

    def success(self, text):
        if not self._quiet:
            self._write(self._stdout, f"Success: {text}")

    def warning(self, text):
        if not self._quiet:
            self._write(self._stderr, f"Warning: {text}")

    def error(self, text):
        self._write(self._stderr, f"Error: {text}")

    def debug(self, text):
        if self._debug:
            self._write(self._stderr, f"Debug: {text}")
