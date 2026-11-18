"""Validation of supplied arguments against a command's synopsis."""

from .errors import AppctlError, UsageError
from .help import render_usage
from .suggest import get_suggestion
from .synopsis import ASSOC, FLAG, GENERIC, POSITIONAL


class ArgumentValidator:
    """Checks positional and associative arguments for one command."""

    def __init__(self, command):
        self.command = command
        self.positionals = command.tokens_of_type(POSITIONAL)
        self.parameters = command.tokens_of_type(ASSOC, FLAG)
        self.accepts_any_assoc = bool(command.tokens_of_type(GENERIC))

    # -- positional -----------------------------------------------------

    def enough_positionals(self, args):
        required = sum(1 for t in self.positionals if not t.optional)
        return len(args) >= required

    def unknown_positionals(self, args):
        if any(t.repeating for t in self.positionals):
            return []
        return list(args[len(self.positionals):])

    # -- associative ----------------------------------------------------

    def assoc_errors(self, assoc, warn):
        """Return fatal errors; drop optional keyed params given no value."""
        errors = []
        for param in self.parameters:
            key = param.name
            if param.type != ASSOC:
                continue
            value = assoc.get(key)
            if not param.optional:
                if value is None or value is True or value is False or value == "":
                    errors.append(f"missing --{key} parameter")
            elif value is True and not param.value_optional:
                warn(f"--{key} parameter needs a value")
                del assoc[key]
        for key in self.unknown_assoc(assoc):
            message = f"unknown --{key} parameter"
            suggestion = get_suggestion(key, [p.name for p in self.parameters])
            if suggestion:
                message += f"\nDid you mean '--{suggestion}'?"
            errors.append(message)
        return errors

    def unknown_assoc(self, assoc):
        if self.accepts_any_assoc:
            return []
        known = {p.name for p in self.parameters}
        return [key for key in assoc if key not in known]

    # -- defaults -------------------------------------------------------

    def apply_defaults(self, args, assoc):
        defaults = self.command.defaults
        for index, token in enumerate(self.positionals):
            if index < len(args):
                continue
            if token.name in defaults and len(args) == index:
                args.append(defaults[token.name])
            else:
                break
        for param in self.parameters:
            if param.name not in assoc and param.name in defaults:
                assoc[param.name] = defaults[param.name]

    # -- entry point ----------------------------------------------------

    def validate(self, args, assoc, warn=lambda message: None):
        """Validate and return ``(args, assoc)`` with defaults applied."""
        args = list(args)
        assoc = dict(assoc)
        if not self.enough_positionals(args):
            raise UsageError(render_usage(self.command))
        extra = self.unknown_positionals(args)
        if extra:
            raise AppctlError("Too many positional arguments: " + " ".join(extra))
        errors = self.assoc_errors(assoc, warn)
        if errors:
            raise AppctlError("Parameter errors:\n" + "\n".join(f" {e}" for e in errors))
        self.apply_defaults(args, assoc)
        return args, assoc
