"""Interpretation of argument values.

Secret: how a raw value is decoded according to ``--format`` and how a
decoding failure is reported without leaking the raw value to the log file.
"""

import json

from . import messages as _messages
from .errors import CliError


def read_value(raw, fmt=None):
    """Decode ``raw`` as JSON when ``fmt`` is ``json``; otherwise return it."""
    if fmt != "json" or not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        raise CliError(_messages.invalid_json(raw), sensitive=True,
                       log_message=_messages.invalid_json(_messages.redacted())) from None
