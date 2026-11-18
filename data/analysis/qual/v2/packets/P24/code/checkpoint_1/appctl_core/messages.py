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
