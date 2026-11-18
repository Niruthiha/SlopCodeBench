"""Failure categories.

Secret: how failure categories map to exit codes and how the diagnostic
line is formatted.
"""


class MtlError(Exception):
    """Base class of all user-facing failures."""

    _label = "runtime_error"
    _code = 4


class DslError(MtlError):
    """The DSL program is syntactically or structurally invalid."""

    _label = "bad_dsl"
    _code = 1


class TypeCheckError(MtlError):
    """A value or expression has an unacceptable type."""

    _label = "type_error"
    _code = 2


class InputError(MtlError):
    """Inputs could not be read (files, CSV structure, CLI arguments)."""

    _label = "bad_io"
    _code = 3


class ExecutionError(MtlError):
    """Evaluation failed at run time (division by zero, non-finite values)."""

    _label = "runtime_error"
    _code = 4


def report(error, stream):
    """Write the one-line diagnostic for `error` and return its exit code."""
    message = " ".join(str(error).split()) or error.__class__.__name__
    stream.write("ERROR:%s:%s\n" % (error._label, message))
    stream.flush()
    return error._code
