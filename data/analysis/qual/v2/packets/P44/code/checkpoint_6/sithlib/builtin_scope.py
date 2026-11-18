"""The builtin scope and Python keywords."""
import builtins
import keyword

from .entries import ValueEntry
from .values import wrap_runtime

KEYWORDS = tuple(keyword.kwlist)


def builtin_entries():
    """Entries for every name in the `builtins` module.

    Names that are also keywords (True, False, None) are offered only as
    keywords, so they are left out here.
    """
    entries = {}
    for name in dir(builtins):
        if keyword.iskeyword(name):
            continue
        entries[name] = ValueEntry(lambda name=name: wrap_runtime(getattr(builtins, name)))
    return entries
