"""Result serialization.

Secret: the wire format of the result (compact JSON with a ``completions``
array of name/complete/type/description objects, newline-terminated).
"""

import json
import sys


def write_completions(completions, stream=None):
    """``completions``: iterable of (name, complete, type, description)."""
    payload = {"completions": [
        {"name": name, "complete": complete, "type": kind, "description": description}
        for name, complete, kind, description in completions
    ]}
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
    stream = stream or sys.stdout
    if hasattr(stream, "buffer"):
        stream.flush()
        stream.buffer.write(text.encode("utf-8"))
        stream.buffer.flush()
    else:
        stream.write(text)
        stream.flush()
