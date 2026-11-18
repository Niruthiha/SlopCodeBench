"""Failure categories.

Secret: how failure categories map to exit codes and how the diagnostic
and warning lines are formatted.
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


class ConfigError(MtlError):
    """The ingest configuration is malformed or inconsistent with the DSL."""

    _label = "config_error"
    _code = 5


class ArtifactError(MtlError):
    """The DSL version is unsupported or the resumable state cannot be used."""

    _label = "artifact_error"
    _code = 6


def report(error, stream):
    """Write the one-line diagnostic for `error` and return its exit code."""
    message = " ".join(str(error).split()) or error.__class__.__name__
    stream.write("ERROR:%s:%s\n" % (error._label, message))
    stream.flush()
    return error._code


def warn(category, message, stream):
    """Write a one-line warning (the run still succeeds)."""
    stream.write("WARNING:%s:%s\n" % (category, " ".join(message.split())))
    stream.flush()
