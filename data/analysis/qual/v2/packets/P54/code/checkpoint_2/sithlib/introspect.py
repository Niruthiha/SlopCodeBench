"""Runtime object introspection.

Secret: how a live Python object is classified (module, class, function or
instance) and how its attributes are enumerated and fetched safely.
"""

import inspect

MODULE = "module"
CLASS = "class"
FUNCTION = "function"
INSTANCE = "instance"


def kind_of(obj):
    if inspect.ismodule(obj):
        return MODULE
    if isinstance(obj, type):
        return CLASS
    if inspect.isroutine(obj):
        return FUNCTION
    return INSTANCE


def type_name(obj):
    """Name of the type of ``obj`` (for describing instances)."""
    return type(obj).__name__


def class_name(cls):
    return getattr(cls, "__name__", type(cls).__name__)


def attribute_names(obj):
    try:
        return [n for n in dir(obj) if isinstance(n, str)]
    except Exception:
        return []


def get_attribute(obj, name):
    """Return ``(True, value)`` or ``(False, None)`` if fetching fails."""
    try:
        return True, getattr(obj, name)
    except BaseException:  # noqa: B902 - descriptors may raise anything
        return False, None


def is_data_descriptor(obj):
    return inspect.isdatadescriptor(obj)


_SAFE_SAMPLE_MODULES = ("builtins",)


def sample_instance(cls):
    """An instance of ``cls`` built without side effects, or None."""
    if getattr(cls, "__module__", None) not in _SAFE_SAMPLE_MODULES:
        return None
    try:
        return cls()
    except BaseException:  # noqa: B902 - constructors may raise anything
        return None
