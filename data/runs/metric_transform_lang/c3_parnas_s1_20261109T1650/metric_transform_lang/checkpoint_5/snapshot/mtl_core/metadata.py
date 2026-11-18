"""Run metadata.

Secret: the metadata document -- its key order, how provenance, input
statistics, the pipeline's shape, UDF signatures, data-quality counts and
the output contract are described, and the sorting rules that make the
document stable across identical runs.
"""

import json
import re
from collections import OrderedDict
from datetime import datetime

from . import program as P
from . import quality as Q
from . import timestamps
from .errors import ExecutionError

_QUALITY_ORDER = (Q.PARSE_TYPE_MISMATCH, Q.TIMESTAMP_PARSE_ERROR, Q.RUNTIME_ERROR, Q.TYPE_ERROR,
                  Q.MISSING_REQUIRED_FIELD, Q.PARQUET_TYPE_MISMATCH)


def file_statistics(units, rows_read, bad_records):
    """canonical path -> (rows_read, rows_valid, rows_bad) of every admitted file.

    rows_read: file path (as named) -> records read; a row is bad when at
    least one bad record was logged for it.
    """
    bad_rows = {}
    for record in bad_records:
        prov = record.provenance
        if prov.row is not None:
            bad_rows.setdefault(prov.file, set()).add(prov.row)
    stats = {}
    for unit in units:
        read = rows_read.get(unit.entry.path, 0)
        bad = min(len(bad_rows.get(unit.entry.path, ())), read)
        stats[unit.path] = (read, read - bad, bad)
    return stats


def build(run, versions, units, stats, source_names, params, options, program, window,
          udfs, strict, bad_records, result):
    """The metadata document as an OrderedDict (see render)."""
    sources = []
    for name in sorted(source_names):
        files = []
        for unit in sorted((u for u in units if u.source == name), key=lambda u: u.path):
            read, valid, bad = stats[unit.path]
            files.append(OrderedDict([
                ("path", unit.path),
                ("fingerprint", unit.fingerprint),
                ("format", unit.entry.format),
                ("rows_read", read),
                ("rows_valid", valid),
                ("rows_bad", bad),
            ]))
        sources.append(OrderedDict([("name", name), ("files", files)]))

    counts = OrderedDict((c, 0) for c in _QUALITY_ORDER)
    for record in bad_records:
        counts[record.classification] = counts.get(record.classification, 0) + 1

    return OrderedDict([
        ("run", OrderedDict([
            ("run_id", run["run_id"]),
            ("started_at", run["started_at"]),
            ("completed_at", run["completed_at"]),
            ("duration_ms", run["duration_ms"]),
            ("resume", run["resume"]),
        ])),
        ("versions", versions),
        ("inputs", OrderedDict([
            ("sources", sources),
            ("params", OrderedDict((k, _value(params[k][1])) for k in sorted(params))),
            ("tz", options["tz"]),
            ("timestamp_format", options["timestamp_format"]),
            ("null_markers", sorted(set(options["null_markers"]) | {""})),
        ])),
        ("pipeline", OrderedDict([
            ("name", program.name),
            ("schema", program.schema_name),
            ("group_by", list(program.group_by.columns) if program.group_by else []),
            ("window", None if window is None else OrderedDict([
                ("duration", window), ("aligned_to_epoch", True)])),
            ("aggregates", sorted(item.alias for item in program.aggregate.items)),
            ("post_agg_calcs", sorted(calc.name for calc in program.post_calcs)),
            ("joins", [_join(join, params) for join in program.joins]),
        ])),
        ("udfs", [OrderedDict([("name", f.name), ("args", list(f.args)),
                               ("returns", f.returns), ("hash", f.hash)])
                  for f in sorted(udfs, key=lambda f: (f.name, f.args, f.returns))]),
        ("quality", OrderedDict([
            ("strict", strict),
            ("bad_record_counts", counts),
        ])),
        ("output", OrderedDict([
            ("shape", "object" if result.scalar else "array"),
            ("row_count", len(result.rows)),
            ("ordering", OrderedDict([
                ("primary", "window_start" if result.windowed else None),
                ("secondary", list(result.group_columns)),
            ])),
            ("key_ordering", OrderedDict([
                ("window_keys_first", True),
                ("aggregate_aliases_lex", True),
                ("post_agg_calcs_lex", True),
            ])),
        ])),
    ])


def render(document):
    try:
        return json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    except ValueError as exc:
        raise ExecutionError("cannot emit metadata: %s" % exc)


def window_duration(program, params):
    """The window width as text such as '1h', or None without a window."""
    spec = program.window
    if spec is None:
        return None
    if spec.param is None:
        return "%d%s" % (spec.amount, spec.unit)
    return _duration_param(params, spec.param, "mhd")


def _duration_param(params, name, units):
    value = params.get(name, (None, None))[1]
    m = re.match(r"^\s*(\d+)\s*([%s])\s*$" % units, value) if isinstance(value, str) else None
    return "%d%s" % (int(m.group(1)), m.group(2)) if m else value


def _join(join, params):
    within = None
    if join.within is not None:
        if join.within.param is None:
            within = "%d%s" % (join.within.amount, join.within.unit)
        else:
            within = _duration_param(params, join.within.param, "smhd")
    keys = [_text(c.left) + "==" + _text(c.right) for c in _conjuncts(join.on)
            if isinstance(c, P.Binary) and c.op == "=="]
    return OrderedDict([("left", join.left), ("right", join.right), ("type", join.kind),
                        ("temporal_within", within), ("on_keys", keys)])


def _conjuncts(expr):
    if isinstance(expr, P.Binary) and expr.op == "&":
        return _conjuncts(expr.left) + _conjuncts(expr.right)
    return [expr]


def _text(expr):
    """Compact canonical source text of an expression."""
    if isinstance(expr, P.ColumnRef):
        return expr.name
    if isinstance(expr, P.Literal):
        if expr.kind == "string":
            return "'%s'" % expr.value
        if expr.kind == "bool":
            return "true" if expr.value else "false"
        return repr(expr.value)
    if isinstance(expr, P.Param):
        return "param('%s')" % expr.name
    if isinstance(expr, P.Cast):
        return "cast(%s as %s)" % (_text(expr.operand), expr.type)
    if isinstance(expr, P.Call):
        return "%s(%s)" % (expr.name, ",".join(_text(a) for a in expr.args))
    if isinstance(expr, P.Unary):
        return expr.op + _nested(expr.operand)
    return "%s%s%s" % (_nested(expr.left), " in " if expr.op == "in" else expr.op,
                       _nested(expr.right))


def _nested(expr):
    text = _text(expr)
    return "(%s)" % text if isinstance(expr, P.Binary) else text


def _value(value):
    if isinstance(value, datetime):
        return timestamps.format_utc(value)
    return value
