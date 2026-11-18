"""Result serialization.

Secret: the wire format of the result (compact JSON with a ``completions``
array of name/complete/type/description objects, a ``definitions`` array of
definition objects, a ``signatures`` array, a ``references`` array, an
``errors`` array, a ``context`` array of enclosing scopes, an
``environments`` array, an environment object, a project configuration
object, or ``changed_files``/``renames`` maps, newline-terminated; or a
unified diff as plain text).
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


def write_errors(errors, stream=None):
    """``errors``: dicts with line, column, until_line, until_column, message."""
    fields = ("line", "column", "until_line", "until_column", "message")
    _write({"errors": [{f: e[f] for f in fields} for e in errors]}, stream)


def write_context(scopes, stream=None):
    """``scopes``: dicts with name, type, line, column (outermost first)."""
    fields = ("name", "type", "line", "column")
    _write({"context": [{f: s[f] for f in fields} for s in scopes]}, stream)


def write_environments(environments, stream=None):
    """``environments``: dicts with executable, version, is_virtualenv."""
    fields = ("executable", "version", "is_virtualenv")
    _write({"environments": [{f: e[f] for f in fields} for e in environments]}, stream)


def write_environment(environment, stream=None):
    """``environment``: dict with executable, version, is_virtualenv, prefix, sys_path."""
    fields = ("executable", "version", "is_virtualenv", "prefix", "sys_path")
    _write({f: environment[f] for f in fields}, stream)


def write_configuration(configuration, stream=None):
    """``configuration``: the project configuration fields."""
    _write(dict(configuration), stream)


def write_changes(changed_files, renames, stream=None):
    """``changed_files``: path -> new content; ``renames``: old path -> new path."""
    _write({"changed_files": changed_files, "renames": renames}, stream)


def write_text(text, stream=None):
    _emit(text, stream)


def _write(payload, stream):
    _emit(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n", stream)


def _emit(text, stream):
    stream = stream or sys.stdout
    if hasattr(stream, "buffer"):
        stream.flush()
        stream.buffer.write(text.encode("utf-8"))
        stream.buffer.flush()
    else:
        stream.write(text)
        stream.flush()
