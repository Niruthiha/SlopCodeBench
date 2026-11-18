"""User-facing message wording.

Secret: the exact text of every error and notice, and the program's display
name.
"""

_PROGRAM = "appctl"


def program_name():
    return _PROGRAM


def _with_suggestion(message, suggestion):
    if suggestion:
        return f"{message}\nDid you mean '{suggestion}'?"
    return message


def unregistered_command(name, suggestion=None):
    return _with_suggestion(
        f"'{name}' is not a registered {_PROGRAM} command. "
        f"See '{_PROGRAM} help' for available commands.",
        suggestion,
    )


def unregistered_subcommand(name, parent, suggestion=None):
    return _with_suggestion(
        f"'{name}' is not a registered subcommand of '{parent}'. "
        f"See '{_PROGRAM} help {parent}' for available subcommands.",
        suggestion,
    )


def too_many_positionals(words):
    return "Too many positional arguments: " + " ".join(words)


def parameter_errors(lines):
    return "Parameter errors:" + "".join(f"\n {line}" for line in lines)


def missing_parameter(key):
    return f"missing --{key} parameter"


def parameter_needs_value(key):
    return f"--{key} parameter needs a value"


def parameter_takes_no_value(key):
    return f"--{key} parameter does not accept a value"


def unknown_parameter(key, suggestion=None):
    message = f"unknown --{key} parameter"
    if suggestion:
        message += f"\nDid you mean '--{suggestion}'?"
    return message


def invalid_synopsis(path, parts):
    return (f"The '{path}' command has an invalid synopsis: "
            + ", ".join(parts))


def global_parameter_error(key, needs_value):
    if needs_value:
        return f"The --{key} global parameter needs a value."
    return f"The --{key} global parameter does not accept a value."


def command_disabled(path):
    return f"The '{path}' command has been disabled."


def deprecated_global_parameter(key):
    return f"The --{key} global parameter is deprecated."


def alias_not_found(name, suggestion=None):
    return _with_suggestion(f"Alias '{name}' not found.", suggestion)


def alias_group_invalid(group, invalid):
    return (f"Group '{group}' contains one or more invalid aliases: "
            + ", ".join(invalid) + ".")


def alias_all_without_aliases():
    return "Cannot use '@all' when no aliases are registered."


def ssh_connection_failed():
    return "Cannot connect over SSH using provided configuration."


def _reason(exc):
    return getattr(exc, "strerror", None) or str(exc)


def config_unwritable(path, exc):
    return f"Unable to write the global config file '{path}': {_reason(exc)}."


def config_unreadable(path, exc):
    return f"Unable to read the config file '{path}': {_reason(exc)}."


def config_unparsable(path, exc):
    return f"Unable to parse the config file '{path}': {exc}"


def invalid_field(name):
    return f"Invalid field: {name}."


def invalid_json(raw):
    return f"Invalid JSON: {raw}"


def redacted():
    return "[redacted]"


def operation_cancelled():
    return "Operation cancelled."


def invalid_format(fmt, supported):
    return f"Invalid format: {fmt}. Supported formats: " + ", ".join(supported)


def directory_uncreatable(path, exc):
    return f"Failed to create directory '{path}': {_reason(exc)}."


def spawned_exit_minus_one():
    return ("Spawned process returned exit code -1, which could be caused by the "
            "signal handling configuration (e.g. SIGCHLD being ignored).")


def unsupported_archive():
    return "Extraction only supported for '.zip' and '.tar.gz' file types."


def archive_not_found(path):
    return f"Archive '{path}' does not exist."


def zip_unavailable():
    return "Extracting a zip file requires a zip archive extension (zipfile)."


def tar_unavailable():
    return "Extracting a tar.gz file requires tar.gz support (tarfile or 'tar')."


def archive_extraction_failed(path, reason):
    return f"Failed to extract '{path}': {reason}"


def tarfile_fallback(reason):
    return f"tarfile extraction failed, falling back to 'tar xz' ({reason})."


def unable_to_copy(relative):
    return f"Unable to copy '{relative}' to current directory."


def overwrite_failed():
    return "There was an error overwriting existing files."


def archive_extracted(archive, destination):
    return f"Extracted '{archive}' to '{destination}'."
