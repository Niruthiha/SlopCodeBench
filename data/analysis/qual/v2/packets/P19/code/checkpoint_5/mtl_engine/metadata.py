"""The --meta-out document: provenance, input statistics, lineage and output shape."""
import json
from datetime import datetime

from . import badrecords as br
from . import udfs
from .state import iso_z
from .timeutil import format_utc
from .versions import RUNTIME_VERSION

ERROR_TYPES = (br.PARSE_TYPE_MISMATCH, br.TIMESTAMP_PARSE_ERROR, br.RUNTIME_ERROR,
               br.TYPE_ERROR, br.MISSING_REQUIRED_FIELD, br.PARQUET_TYPE_MISMATCH)


def build(run_state, program, args, param_values, null_markers, sink, document):
    """Assemble the metadata object (key order as specified)."""
    started = run_state.started_at
    completed = run_state.completed_at
    duration_ms = max(0, round((completed - started).total_seconds() * 1000))
    return {
        "run": {
            "run_id": run_state.run_id,
            "started_at": iso_z(started),
            "completed_at": iso_z(completed),
            "duration_ms": duration_ms,
            "resume": bool(run_state.resume),
        },
        "versions": {
            "mtl_runtime": RUNTIME_VERSION,
            "dsl_version": run_state.dsl_version,
            "dsl_sha256": run_state.dsl_sha256,
            "ingest_config_sha256": run_state.config_sha256,
        },
        "inputs": {
            "sources": _sources(run_state.files, sink),
            "params": {name: _json_value(param_values[name].value)
                       for name in sorted(param_values)},
            "tz": args.tz,
            "timestamp_format": args.timestamp_format,
            "null_markers": sorted(null_markers),
        },
        "pipeline": _pipeline(program),
        "udfs": udfs.metadata(),
        "quality": {
            "strict": bool(args.strict),
            "bad_record_counts": _bad_counts(sink),
        },
        "output": _output(program, document),
    }


def serialize(meta):
    return json.dumps(meta, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def _sources(files, sink):
    bad_rows = {}
    for record in sink.records:
        origin = record.origin
        bad_rows.setdefault(origin.path, set()).add((origin.line, origin.row_index))
    by_source = {}
    for f in files:
        rows_bad = min(len(bad_rows.get(f.display, ())), f.rows_read)
        by_source.setdefault(f.source, []).append({
            "path": f.path,
            "fingerprint": f.fingerprint,
            "format": f.format,
            "rows_read": f.rows_read,
            "rows_valid": f.rows_read - rows_bad,
            "rows_bad": rows_bad,
        })
    return [{"name": name, "files": sorted(entries, key=lambda e: e["path"])}
            for name, entries in sorted(by_source.items())]


def _pipeline(program):
    window = None
    if program.window is not None:
        window = {"duration": f"{program.window.amount}{program.window.unit}",
                  "aligned_to_epoch": True}
    return {
        "name": program.name,
        "schema": program.schema_name,
        "group_by": list(program.group_columns),
        "window": window,
        "aggregates": sorted(item.alias for item in program.aggregate.items),
        "post_agg_calcs": sorted(calc.name for calc in program.post_calcs),
        "joins": [{"left": join.left, "right": join.right, "type": join.join_type,
                   "temporal_within": getattr(join, "within_text", None),
                   "on_keys": list(getattr(join, "key_texts", []))}
                  for join in program.joins],
    }


def _bad_counts(sink):
    counts = {name: 0 for name in ERROR_TYPES}
    for record in sink.records:
        counts[record.error_type] = counts.get(record.error_type, 0) + 1
    return counts


def _output(program, document):
    is_array = isinstance(document, list)
    return {
        "shape": "array" if is_array else "object",
        "row_count": len(document) if is_array else 1,
        "ordering": {
            "primary": "window_start" if program.window is not None else None,
            "secondary": list(program.group_columns),
        },
        "key_ordering": {
            "window_keys_first": True,
            "aggregate_aliases_lex": True,
            "post_agg_calcs_lex": True,
        },
    }


def _json_value(value):
    if isinstance(value, datetime):
        return format_utc(value)
    return value
