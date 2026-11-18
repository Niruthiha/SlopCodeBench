"""Inferred values: what an expression evaluates to, statically."""
import inspect

MODULE = "module"
CLASS = "class"
FUNCTION = "function"
INSTANCE = "instance"


class Value:
    kind = None

    @property
    def type_name(self):
        return None

    @property
    def key(self):
        """Identity used to de-duplicate unions of inferred values."""
        return (type(self).__name__, id(self._identity()))

    def _identity(self):
        return self


class LocalModule(Value):
    """A module parsed from a project source file."""

    kind = MODULE

    def __init__(self, context):
        self.context = context

    def _identity(self):
        return self.context


class RuntimeModule(Value):
    """An installed module, imported for introspection."""

    kind = MODULE

    def __init__(self, obj):
        self.obj = obj

    def _identity(self):
        return self.obj


class LocalClass(Value):
    """A class defined by a `class` statement in parsed source."""

    kind = CLASS

    def __init__(self, scope):
        self.scope = scope

    def _identity(self):
        return self.scope

    @property
    def node(self):
        return self.scope.node

    @property
    def name(self):
        return self.scope.node.name


class LocalFunction(Value):
    """A `def` or `lambda` from parsed source, optionally bound to `self`/`cls`."""

    kind = FUNCTION

    def __init__(self, scope, bound=None):
        self.scope = scope
        self.bound = bound

    def _identity(self):
        return self.scope

    @property
    def node(self):
        return self.scope.node


class LocalInstance(Value):
    """An instance of a local class; `init_args` maps `__init__` parameters to values."""

    kind = INSTANCE

    def __init__(self, cls, init_args=None):
        self.cls = cls
        self.init_args = init_args

    def _identity(self):
        return self.cls.scope

    @property
    def type_name(self):
        return self.cls.name


class RuntimeClass(Value):
    kind = CLASS

    def __init__(self, obj):
        self.obj = obj

    def _identity(self):
        return self.obj


class RuntimeFunction(Value):
    kind = FUNCTION

    def __init__(self, obj):
        self.obj = obj

    def _identity(self):
        return self.obj


class RuntimeInstance(Value):
    """An instance of a runtime class (also used for literals)."""

    kind = INSTANCE

    def __init__(self, cls):
        self.cls = cls

    def _identity(self):
        return self.cls

    @property
    def type_name(self):
        return self.cls.__name__


def unique(values):
    """`values` without duplicates (by identity key), in order."""
    seen = set()
    result = []
    for value in values:
        if value is not None and value.key not in seen:
            seen.add(value.key)
            result.append(value)
    return result


def wrap_runtime(obj):
    """Wrap a live Python object as a Value (None for opaque data descriptors)."""
    if inspect.ismodule(obj):
        return RuntimeModule(obj)
    if inspect.isclass(obj):
        return RuntimeClass(obj)
    origin = getattr(obj, "__origin__", None)
    if inspect.isclass(origin):  # generic aliases such as typing.List or list[int]
        return RuntimeClass(origin)
    if callable(obj):
        return RuntimeFunction(obj)
    if inspect.isdatadescriptor(obj):
        return None
    return RuntimeInstance(type(obj))


# Builtin types whose attributes are introspected on a real (empty) instance,
# so that e.g. `(1).real` is known to be an int rather than a descriptor.
_SAMPLE_TYPES = (bool, int, float, complex, str, bytes, bytearray, list, tuple, dict, set,
                 frozenset, type(None))


def runtime_sample(cls):
    """An instance of `cls` to introspect, or the class itself."""
    if cls in _SAMPLE_TYPES:
        return cls()
    return cls
