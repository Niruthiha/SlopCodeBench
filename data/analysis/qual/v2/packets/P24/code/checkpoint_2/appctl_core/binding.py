"""Argument validation and binding.

Secret: the order in which argument checks run, which conditions count as
errors, how associative-argument errors are batched, and when defaults are
filled in.
"""

from . import messages as _messages
from .errors import CliError, MissingPositional
from .suggest import suggest
from .synopsis import Synopsis


class BoundArguments:
    """Validated arguments with defaults applied."""

    def __init__(self, positionals, options):
        self._positionals = list(positionals)
        self._options = dict(options)

    @property
    def positionals(self):
        return list(self._positionals)

    def positional(self, index, default=None):
        if index < len(self._positionals):
            return self._positionals[index]
        return default

    def option(self, name, default=None):
        return self._options.get(name, default)

    def has_option(self, name):
        return name in self._options

    def options(self):
        return dict(self._options)


def _check_positionals(synopsis, words):
    if len(words) < synopsis.required_positional_count():
        raise MissingPositional()
    limit = synopsis.positional_limit()
    if limit is not None and len(words) > limit:
        raise CliError(_messages.too_many_positionals(words[limit:]))


def _bind_options(synopsis, options):
    bound = {}
    needs_value, takes_no_value, unknown = [], [], []
    for name, value in options:
        key, interpreted, status = synopsis.interpret(name, value)
        if status == Synopsis.OK:
            bound[key] = interpreted
        elif status == Synopsis.NEEDS_VALUE:
            bound.pop(key, None)
            needs_value.append(key)
        elif status == Synopsis.TAKES_NO_VALUE:
            takes_no_value.append(key)
        elif name not in unknown:
            unknown.append(name)

    required = synopsis.required_option_names()
    errors = [_messages.missing_parameter(key)
              for key in required if key not in bound]
    errors += [_messages.parameter_needs_value(key)
               for key in dict.fromkeys(needs_value)
               if key not in required and key not in bound]
    errors += [_messages.parameter_takes_no_value(key)
               for key in dict.fromkeys(takes_no_value)]
    generic = synopsis.requires_generic_option()
    if generic and not any(k not in synopsis.option_names() for k in bound):
        errors.append(_messages.missing_parameter(generic))
    known = synopsis.option_names()
    errors += [_messages.unknown_parameter(key, suggest(key, known))
               for key in unknown]
    if errors:
        raise CliError(_messages.parameter_errors(errors))
    return bound


def _apply_defaults(synopsis, words, options, defaults):
    words = list(words)
    names = synopsis.positional_names()
    for name in names[len(words):]:
        if name not in defaults:
            break
        words.append(defaults[name])
    for name in synopsis.option_names():
        if name not in options and name in defaults:
            options[name] = defaults[name]
    return words, options


def bind(path, synopsis, defaults, words, options):
    """Validate ``words`` and ``options`` against ``synopsis``.

    ``options`` is a sequence of ``(name, value)`` pairs where ``value`` is a
    string or ``None`` (no ``=`` given). Raises ``MissingPositional`` when
    required positionals are absent and ``CliError`` for other problems.
    """
    malformed = synopsis.malformed_parts()
    if malformed:
        raise CliError(_messages.invalid_synopsis(path, malformed))
    _check_positionals(synopsis, list(words))
    bound = _bind_options(synopsis, options)
    words, bound = _apply_defaults(synopsis, words, bound, dict(defaults))
    return BoundArguments(words, bound)
