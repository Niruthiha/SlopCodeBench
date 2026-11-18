"""Interpreter namespaces.

Secret: the format of a namespaces file (a JSON array of objects mapping
names to descriptions of runtime values with ``type``, ``value``,
``module``, ``name`` and ``attributes`` fields) and how a malformed file or
entry is treated (the file is rejected; an odd entry is read leniently).
"""

import json


class NamespaceError(Exception):
    """The namespaces file cannot be used."""


class Entry:
    """What is known about one runtime value."""

    def __init__(self, type_name, value=None, module=None, name=None, attributes=()):
        self.type = type_name
        self.value = value
        self.module = module
        self.name = name
        self.attributes = list(attributes)

    def full_name(self, key):
        name = self.name or key
        if self.module and self.type != "module":
            return "%s.%s" % (self.module, name)
        return name


def load(path):
    """The namespaces stored in the file at ``path``: a list of dicts mapping
    names to Entry objects, in search order."""
    try:
        with open(path, "rb") as handle:
            data = json.loads(handle.read().decode("utf-8-sig"))
    except OSError as exc:
        raise NamespaceError("cannot read namespaces file %s: %s" % (path, exc))
    except ValueError as exc:
        raise NamespaceError("namespaces file %s is not valid JSON: %s" % (path, exc))
    if not isinstance(data, list) or not all(isinstance(n, dict) for n in data):
        raise NamespaceError("namespaces file %s must hold a JSON array of objects" % path)
    return [{name: _entry(description) for name, description in namespace.items()}
            for namespace in data]


def _entry(description):
    if isinstance(description, str):
        return Entry(description)
    if not isinstance(description, dict):
        return Entry(type(description).__name__ if description is not None else "NoneType",
                     value=json.dumps(description))
    type_name = description.get("type")
    attributes = description.get("attributes")
    return Entry(type_name if isinstance(type_name, str) and type_name else "object",
                 value=_text(description.get("value")),
                 module=_text(description.get("module")),
                 name=_text(description.get("name")),
                 attributes=[a for a in attributes if isinstance(a, str)]
                 if isinstance(attributes, list) else ())


def _text(value):
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value)
