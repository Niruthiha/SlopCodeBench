"""DSL versions.

Secret: the shape of the `mtl_version` header, which language version
introduced each construct, the compatibility rules (unsupported majors,
higher minors, constructs newer than the declared version) and when an
older declared version earns a warning.
"""

import re
from collections import namedtuple

from . import program as P
from .dsl_parser import is_builtin_function
from .errors import ArtifactError, DslError

RUNTIME_VERSION = "1.5.0"

Version = namedtuple("Version", "major minor")
Version.__str__ = lambda v: "%d.%d" % v

SUPPORTED = Version(1, 5)
_PART5 = Version(1, 5)

_HEADER_WORD = re.compile(r"^\s*mtl_version(?![A-Za-z0-9_])")
_HEADER = re.compile(r"^\s*mtl_version[ \t]+(\d+)\.(\d+)[ \t]*(#.*)?$")


def read_header(text):
    """(declared Version, DSL text with the header line blanked out).

    The header must be the first line that is neither blank nor a comment.
    """
    lines = text.split("\n")
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not _HEADER_WORD.match(line):
            raise ArtifactError("line %d: missing version header; the DSL must start with "
                                "'mtl_version <major>.<minor>'" % (index + 1))
        m = _HEADER.match(line.rstrip("\r"))
        if not m:
            raise DslError("line %d: invalid version header, expected "
                           "'mtl_version <major>.<minor>'" % (index + 1))
        version = Version(int(m.group(1)), int(m.group(2)))
        if version.major != SUPPORTED.major:
            raise ArtifactError("unsupported mtl_version %s: this runtime supports %d.x "
                                "(up to %s)" % (version, SUPPORTED.major, SUPPORTED))
        lines[index] = ""
        return version, "\n".join(lines)
    raise ArtifactError("missing version header; the DSL must start with "
                        "'mtl_version <major>.<minor>'")


def check_features(program, declared):
    """Raise DslError if the program uses a construct newer than `declared`."""
    newest = None
    for needed, what in _features(program):
        if needed > declared and (newest is None or needed > newest[0]):
            newest = (needed, what)
    if newest is not None:
        raise DslError("%s requires mtl_version %s or later, but the DSL declares %s"
                       % (newest[1], newest[0], declared))


def warning(declared, uses_part5):
    """One-line warning text for an older declared minor version, or None."""
    if declared >= SUPPORTED:
        return None
    message = ("DSL declares mtl_version %s, older than this runtime's %s; constructs are "
               "gated at %s but runtime semantics are those of %s" % (declared, SUPPORTED,
                                                                     declared, SUPPORTED))
    if uses_part5 and declared < _PART5:
        message += "; resumable state and run metadata are mtl_version %s features" % _PART5
    return message


def _features(program):
    """(minimum Version, description) of each versioned construct the program uses."""
    v12, v13, v14 = Version(1, 2), Version(1, 3), Version(1, 4)
    if program.joins:
        yield v14, "join"
    if program.sources is not None:
        yield v14, "a sources block"
    if program.scoped:
        yield v14, "a with block"
    if program.schemas:
        yield v12, "a schema block"
    if program.params:
        yield v12, "a params block"
    if program.calcs:
        yield v12, "calc"
    if program.window is not None and program.window.param is not None:
        yield v12, "window(param(...))"
    for item in program.aggregate.items:
        if item.function == "count" and item.column is not None:
            yield v13, "count(<column>)"
    if program.name is not None:
        yield v12, "a pipeline block"
    for top in P.program_expressions(program):
        for node in P.walk(top):
            if isinstance(node, P.Param):
                yield v12, "param()"
            elif isinstance(node, P.Cast):
                yield v12, "cast()"
            elif isinstance(node, P.Call):
                if node.name in ("lag", "lead"):
                    yield v12, "%s()" % node.name
                elif node.name == "coalesce":
                    yield v13, "coalesce()"
                elif not is_builtin_function(node.name):
                    yield v14, "user-defined function %s()" % node.name
