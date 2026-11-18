"""Exception types shared by several module interfaces."""


class CliError(Exception):
    """A user-facing failure: the message is reported as an error and the
    process exits with ``exit_code``.

    ``message`` may be a list of lines, which is reported as a multi-line
    error. A ``sensitive`` error contains user-supplied material that must
    never reach the log file; ``log_message`` is an optional redacted form
    that may be logged instead.
    """

    def __init__(self, message, exit_code=1, sensitive=False, log_message=None):
        lines = None
        if isinstance(message, (list, tuple)):
            lines = [str(line) for line in message]
            message = "\n".join(lines)
        super().__init__(message)
        self.message = message
        self.lines = lines
        self.exit_code = exit_code
        self.sensitive = sensitive
        self.log_message = log_message


class MissingPositional(Exception):
    """Raised when a command did not receive all of its required positional
    arguments; the caller is expected to show that command's usage."""


class Halt(Exception):
    """Stops the invocation with ``exit_code`` without reporting anything
    (the cause has already been shown, e.g. by a child process)."""

    def __init__(self, exit_code):
        super().__init__(exit_code)
        self.exit_code = exit_code
