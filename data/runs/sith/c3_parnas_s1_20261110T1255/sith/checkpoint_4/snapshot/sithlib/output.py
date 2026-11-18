"""Result serialization.

Secret: the wire format of the result (compact JSON with a ``completions``
array of name/complete/type/description objects, a ``definitions`` array of
definition objects, a ``signatures`` array, or a ``references`` array,
newline-terminated).
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


def write_signatures(signatures, stream=None):
    """``signatures``: dicts with name, params, index, description, docstring."""
    fields = ("name", "params", "index", "description", "docstring")
    _write({"signatures": [{f: s[f] for f in fields} for s in signatures]}, stream)


def write_references(references, stream=None):
    """``references``: dicts with module_path, line, column, is_definition."""
    fields = ("module_path", "line", "column", "is_definition")
    _write({"references": [{f: r[f] for f in fields} for r in references]}, stream)


def write_search_results(definitions, stream=None):
    """``definitions``: definition dicts (their docstrings are left out)."""
    fields = [f for f in _DEFINITION_FIELDS if f != "docstring"]
    found = [{f: d[f] for f in fields} for d in definitions]
    _write({"definitions": found, "results": found}, stream)


def write_names(definitions, stream=None):
    """``definitions``: definition dicts with ``is_definition``."""
    fields = _DEFINITION_FIELDS + ("is_definition",)
    found = [{f: d[f] for f in fields} for d in definitions]
    _write({"definitions": found, "names": found}, stream)


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
