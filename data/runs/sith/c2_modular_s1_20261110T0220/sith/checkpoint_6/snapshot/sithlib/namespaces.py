"""Interpreter mode: runtime namespaces describing the live objects of a REPL session.

Namespaces are a fallback for static analysis: a name is looked up in them
only when static analysis cannot resolve it, and the first namespace binding
a name wins.
"""
import builtins
import inspect
import json

from .errors import SithError
from .values import RuntimeInstance, Value

# Type of the completions offered for the `attributes` of a namespace object.
ATTRIBUTE_TYPE = "statement"


def runtime_description(kind):
    return f"{kind} (runtime)"


class NamespaceObject:
    """One runtime value: the entry for `key` in a namespace."""

    def __init__(self, key, data):
        if not isinstance(data, dict):
            data = {"type": type(data).__name__ if data is not None else "NoneType",
                    "value": json.dumps(data)}
        self.key = key
        self.type = _text(data.get("type")) or "object"
        self.value = _text(data.get("value"))
        self.module = _text(data.get("module"))
        self.name = _text(data.get("name")) or key
        attributes = data.get("attributes")
        self.attributes = [a for a in attributes if isinstance(a, str) and a] \
            if isinstance(attributes, list) else []

    @property
    def full_name(self):
        if self.type == "module":
            return self.name if self.name != self.key else (self.module or self.key)
        return f"{self.module}.{self.name}" if self.module else self.name


def _text(value):
    return value if isinstance(value, str) else ""


class Namespaces:
    """An ordered list of namespaces ({name: NamespaceObject})."""

    def __init__(self, namespaces):
        self.namespaces = namespaces

    def lookup(self, name):
        """The object bound to `name` by the first namespace defining it, or None."""
        for namespace in self.namespaces:
            if name in namespace:
                return namespace[name]
        return None

    def objects(self):
        """{name: object}, the first namespace defining a name winning."""
        result = {}
        for namespace in self.namespaces:
            for name, obj in namespace.items():
                result.setdefault(name, obj)
        return result


def load_namespaces(path):
    """Parse a `--namespaces` file: a JSON array of objects (SithError when invalid)."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as error:
        raise SithError(f"namespaces file not found: {path}") from error
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise SithError(f"cannot read namespaces file {path}: {error}") from error
    if not isinstance(data, list) or not all(isinstance(n, dict) for n in data):
        raise SithError(f"invalid namespaces file {path}: expected a JSON array of objects")
    return Namespaces([{str(key): NamespaceObject(str(key), value) for key, value in n.items()}
                       for n in data])


class NamespaceValue(Value):
    """A runtime value known only from a namespace description."""

    def __init__(self, obj):
        self.obj = obj
        self._resolved = {}

    @property
    def kind(self):
        return self.obj.type

    @property
    def type_name(self):
        return self.obj.type

    def _identity(self):
        return self.obj

    def resolve(self, inferrer):
        """The static value the description points to (e.g. an importable module), or None."""
        key = id(inferrer)
        if key not in self._resolved:
            self._resolved[key] = None
            self._resolved[key] = self._resolve(inferrer)
        return self._resolved[key]

    def _resolve(self, inferrer):
        obj = self.obj
        importer = inferrer.importer
        if obj.type == "module":
            for dotted in (obj.name, obj.module, obj.key):
                module = importer.import_absolute(dotted) if dotted else None
                if module is not None:
                    return module
            return None
        if obj.module and obj.module != "__main__":
            base = importer.import_absolute(obj.module)
            if base is not None:
                found = inferrer.members.member(base, obj.name)
                if found is not None:
                    return found
        cls = getattr(builtins, obj.type, None)
        if inspect.isclass(cls):
            return RuntimeInstance(cls)
        return None


class NamespaceBinding:
    """Stands in for a binding when a name is only bound by a namespace."""

    kind = "namespace"

    def __init__(self, obj):
        self.obj = obj
        self.name = obj.key
        self._value = NamespaceValue(obj)

    def value(self):
        return self._value


class NamespaceEntry:
    """A completion candidate bound by a namespace."""

    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value

    def describe(self, name):
        return self._value.kind, runtime_description(self._value.kind)


class AttributeEntry:
    """A completion candidate listed in the `attributes` of a namespace object."""

    def value(self):
        return None

    def describe(self, name):
        return ATTRIBUTE_TYPE, runtime_description(ATTRIBUTE_TYPE)
