"""Exception types shared by several module interfaces."""


class CliError(Exception):
    """A user-facing failure: the message is reported as an error and the
    process exits with ``exit_code``."""

    def __init__(self, message, exit_code=1):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class MissingPositional(Exception):
    """Raised when a command did not receive all of its required positional
    arguments; the caller is expected to show that command's usage."""
