"""Exception types used across sith."""


class SithError(Exception):
    """A user-facing error: reported on STDERR and turned into exit code 1."""
