"""Exception types used to signal user-facing failures."""


class AppctlError(Exception):
    """A fatal error reported as ``Error: <message>`` on STDERR.

    A ``sensitive`` error carries user-supplied material and is never
    persisted to the log file.
    """

    def __init__(self, message, exit_code=1, sensitive=False):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.sensitive = sensitive


class MultiLineError(AppctlError):
    """A fatal error whose lines are shown in a highlighted box."""

    def __init__(self, lines, exit_code=1, sensitive=False):
        self.lines = [str(line) for line in lines]
        super().__init__("\n".join(self.lines), exit_code, sensitive)


class CommandNotFoundError(AppctlError):
    """Raised when a command or subcommand cannot be resolved."""


class UsageError(AppctlError):
    """Raised when a command must print its usage on STDOUT and fail."""

    def __init__(self, usage, exit_code=1):
        super().__init__(usage, exit_code)
        self.usage = usage


class SynopsisError(ValueError):
    """Raised when a command is registered with a malformed synopsis."""
