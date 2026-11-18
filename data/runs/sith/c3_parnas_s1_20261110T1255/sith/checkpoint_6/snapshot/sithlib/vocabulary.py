"""Language vocabulary.

Secret: where the builtin namespace and the keyword list come from (here:
the running interpreter's ``builtins`` and ``keyword`` modules).
"""

import builtins
import keyword


def keywords():
    return list(keyword.kwlist)


def builtin_namespace():
    """The object whose attributes are the builtin names."""
    return builtins


def builtin_names():
    """Builtin names, excluding those that are reserved keywords."""
    reserved = set(keyword.kwlist)
    return [name for name in dir(builtins) if name not in reserved]
