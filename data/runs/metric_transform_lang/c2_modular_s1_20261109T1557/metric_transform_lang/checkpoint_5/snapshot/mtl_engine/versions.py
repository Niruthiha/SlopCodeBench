"""The `mtl_version` header and gating of DSL constructs by declared version."""
import re

from .ast_nodes import Call, Cast, ColumnRef
from .errors import ArtifactError, DSLSyntaxError
from .functions import ARITY
from .typecheck import walk

RUNTIME_VERSION = "1.5.0"
# Newest DSL version this runtime implements; any 1.x minor is accepted.
SUPPORTED = (1, 5)

_KEYWORD_RE = re.compile(r"mtl_version(?![A-Za-z0-9_])")
_HEADER_RE = re.compile(r"mtl_version[ \t]+(\d+)\.(\d+)[ \t]*(#.*)?$")

PART2 = (1, 2)
PART3 = (1, 3)
PART4 = (1, 4)


def show(version):
    return f"{version[0]}.{version[1]}"


def split_header(text):
    """Return ((major, minor), text with the header line blanked out).

    The header must be the first line that is neither blank nor a comment.
    """
    lines = text.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not _KEYWORD_RE.match(stripped):
            break
        match = _HEADER_RE.match(stripped)
        if match is None:
            raise DSLSyntaxError(f"line {idx + 1}: invalid version header {stripped!r}; "
                                 "expected 'mtl_version <MAJOR>.<MINOR>'")
        version = (int(match.group(1)), int(match.group(2)))
        if version[0] != SUPPORTED[0]:
            raise ArtifactError(f"unsupported DSL major version {show(version)}; this runtime "
                                f"supports {SUPPORTED[0]}.x up to {show(SUPPORTED)}")
        lines[idx] = "\n"  # keep line numbers of the remaining statements
        return version, "".join(lines)
    raise ArtifactError("missing 'mtl_version <MAJOR>.<MINOR>' header on the first "
                        "non-comment line of the DSL")


def check_features(program, version):
    """DSL error for the first construct that needs a newer minor than declared."""
    too_new = [(line, need, what) for need, what, line in _features(program) if version < need]
    if too_new:
        line, need, what = min(too_new, key=lambda f: f[0])
        raise DSLSyntaxError(f"line {line}: {what} requires mtl_version {show(need)} or later, "
                             f"but the DSL declares {show(version)}")


def older_minor_warning(version):
    """Warning text when the declared minor predates this runtime's behavior."""
    if version >= SUPPORTED:
        return None
    return (f"WARNING:version:DSL declares mtl_version {show(version)}; constructs and "
            f"semantics of later minors (up to {show(SUPPORTED)}) are not enabled for it")


def _features(program):
    for decl in program.schemas.values():
        yield PART2, "schema block", decl.line
        for field in decl.fields:
            if field.expr is not None:
                yield from _expr_features(field.expr, field.line)
    for decl in program.params:
        yield PART2, "params block", decl.line
    for calc in program.calcs:
        yield PART2, "calc", calc.line
        yield from _expr_features(calc.expr, calc.line)
    if program.window is not None and program.window.param is not None:
        yield PART2, "param() window durations", program.window.line
    for op in program.row_ops:
        expr = getattr(op, "predicate", None) or getattr(op, "expr", None)
        yield from _expr_features(expr, op.line)
    for item in program.aggregate.items:
        if item.func == "count" and item.column is not None:
            yield PART3, "count(column)", item.line
    if program.sources is not None:
        yield PART4, "sources block", program.sources.line
    for block in program.with_blocks:
        yield PART4, "with block", block.line
        for calc in block.calcs:
            yield from _expr_features(calc.expr, calc.line)
        for flt in block.filters:
            yield from _expr_features(flt.predicate, flt.line)
    for join in program.joins:
        yield PART4, "join", join.line
        yield from _expr_features(join.on, join.line)
        for proj in join.projections:
            yield from _expr_features(proj.expr, proj.line)


def _expr_features(expr, line):
    for node in walk(expr):
        if isinstance(node, Call):
            if node.name in ("param", "lag", "lead"):
                yield PART2, f"{node.name}()", node.line
            elif node.name == "coalesce":
                yield PART3, "coalesce()", node.line
            elif node.name not in ARITY:
                yield PART4, f"user-defined function {node.name}()", node.line
        elif isinstance(node, Cast):
            yield PART3, "cast()", node.line
        elif isinstance(node, ColumnRef) and node.qualifier is not None:
            yield PART4, f"qualified column '{node.qualifier}.{node.name}'", line
