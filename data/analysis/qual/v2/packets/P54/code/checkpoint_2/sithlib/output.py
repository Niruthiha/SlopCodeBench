"""Result serialization.

Secret: the wire format of the result (compact JSON with a ``completions``
array of name/complete/type/description objects, or a ``definitions`` array
of definition objects, newline-terminated).
"""

import json
import sys


_DEFINITION_FIELDS = ("name", "type", "full_name", "module_path", "line", "column",
                      "description", "docstring")


def write_completions(completions, stream=None):
    """``completions``: iterable of (name, complete, type, description)."""
    payload = {"completions": [
        {"name": name, "complete": complete, "type": kind, "description": description}
        for name, complete, kind, description in completions
    ]}
    _write(payload, stream)


def write_definitions(definitions, stream=None):
    """``definitions``: iterable of dicts with the definition fields."""
    payload = {"definitions": [{field: d[field] for field in _DEFINITION_FIELDS}
                               for d in definitions]}
    _write(payload, stream)


def _write(payload, stream):
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
    stream = stream or sys.stdout
    if hasattr(stream, "buffer"):
        stream.flush()
        stream.buffer.write(text.encode("utf-8"))
        stream.buffer.flush()
    else:
        stream.write(text)
        stream.flush()
