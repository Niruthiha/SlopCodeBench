#!/usr/bin/env python3
"""MTL: roll up sales events (CSV, TSV, Parquet) according to a small pipeline DSL.

    python mtl.py --input <path-or-glob> [--input <path-or-glob> ...]
                  --dsl <path-or-> [--out <path-or-stdout>]
    python mtl.py --dsl <path-or-> --ingest-config <path> [--out <path-or-stdout>]
                  [--meta-out <path>] [--state-dir <dir>] [--resume]
                  [--fingerprint <mtime_size|xxhash64>]
                  [--checkpoint-granularity <file|rowgroup|line>]
                  [--tz <IANA>] [--timestamp-format <str>] [--strict]
                  [--param key=value ...] [--udf <path> ...] [--recursive]
                  [--format <csv|tsv|parquet|auto>] [--nulls "<markers>"]
                  [--bad-records-out <path>]
"""

import argparse
import hashlib
import os
import sys
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mtl_core import (checkpoints, declarations, engine, expressions, fingerprints,  # noqa: E402
                      ingest, inputs, joins, metadata, output, sources, timestamps, udfs,
                      versioning)
from mtl_core.dsl_parser import parse_program  # noqa: E402
from mtl_core.errors import (ArtifactError, ConfigError, DslError, InputError,  # noqa: E402
                             MtlError, report, warn)
from mtl_core.quality import BadRecordLog  # noqa: E402
from mtl_core.timestamps import TimestampParser  # noqa: E402


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError("invalid arguments: %s" % message)


def _parse_args(argv):
    parser = _ArgumentParser(prog="mtl.py", description=__doc__)
    parser.add_argument("--input", dest="inputs", action="append", nargs="+", default=[],
                        metavar="path-or-glob")
    parser.add_argument("--csv", dest="csv_inputs", action="append", nargs="+", default=[],
                        help=argparse.SUPPRESS)
    parser.add_argument("--dsl", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--tz", default="UTC")
    parser.add_argument("--timestamp-format", dest="timestamp_format", default=None)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--param", dest="params", action="append", nargs="+", default=[],
                        metavar="key=value")
    parser.add_argument("--udf", dest="udfs", action="append", nargs="+", default=[],
                        metavar="path")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--format", dest="format", default=inputs.AUTO)
    parser.add_argument("--nulls", default=None)
    parser.add_argument("--bad-records-out", dest="bad_records_out", default=None)
    parser.add_argument("--ingest-config", dest="ingest_config", default=None)
    parser.add_argument("--meta-out", dest="meta_out", default=None)
    parser.add_argument("--state-dir", dest="state_dir", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fingerprint", default=fingerprints.MTIME_SIZE)
    parser.add_argument("--checkpoint-granularity", dest="granularity", default="file")
    args = parser.parse_args(argv)
    args.format = args.format.strip().lower()
    if args.format not in inputs.FORMATS:
        raise InputError("invalid arguments: --format must be one of %s"
                         % ", ".join(inputs.FORMATS))
    args.fingerprint = args.fingerprint.strip().lower()
    if args.fingerprint not in fingerprints.SCHEMES:
        raise InputError("invalid arguments: --fingerprint must be one of %s"
                         % ", ".join(fingerprints.SCHEMES))
    args.granularity = args.granularity.strip().lower()
    if args.granularity not in checkpoints.GRANULARITIES:
        raise InputError("invalid arguments: --checkpoint-granularity must be one of %s"
                         % ", ".join(checkpoints.GRANULARITIES))
    args.specs = ([(p, None) for group in args.inputs for p in group]
                  + [(p, inputs.CSV) for group in args.csv_inputs for p in group])
    args.udfs = [p for group in args.udfs for p in group]
    pairs = [pair for group in args.params for pair in group]
    args.params = declarations.parse_cli_params(pairs)
    if args.params is None:
        raise InputError("invalid arguments: --param expects key=value")
    return args


def _read_dsl(source):
    """(raw bytes, text) of the DSL."""
    try:
        if source == "-":
            data = sys.stdin.buffer.read()
        else:
            with open(source, "rb") as handle:
                data = handle.read()
    except OSError as exc:
        raise InputError("cannot read DSL %r: %s" % (source, exc.strerror or exc))
    try:
        return data, data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("DSL %r is not valid UTF-8" % source)


def _sha256_of_file(path):
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError as exc:
        raise InputError("cannot read %r: %s" % (path, exc.strerror or exc))


def _write(destination, text):
    data = text.encode("utf-8")
    if destination is None or destination == "-":
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return
    try:
        with open(destination, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        raise InputError("cannot write output %r: %s" % (destination, exc.strerror or exc))


def _utc_now():
    return datetime.now(timezone.utc)


def _iso(instant):
    return instant.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (instant.microsecond // 1000)


class _Run:
    """What every code path shares: the versioned DSL, UDFs, state and the final writes."""

    def __init__(self, args, dsl_bytes, version):
        self.args = args
        self.started = _utc_now()
        self.clock = time.monotonic()
        self.version = version
        self.dsl_sha256 = hashlib.sha256(dsl_bytes).hexdigest()
        self.udfs = udfs.load(args.udfs)
        expressions.use_functions(self.udfs)
        self.checkpoints = None

    def parse(self, dsl_text):
        program = parse_program(dsl_text, self.udfs.arities())
        versioning.check_features(program, self.version)
        return program

    def open_checkpoints(self, program, config_sha256):
        args = self.args
        self.versions = OrderedDict([
            ("mtl_runtime", versioning.RUNTIME_VERSION),
            ("dsl_version", str(self.version)),
            ("dsl_sha256", self.dsl_sha256),
            ("ingest_config_sha256", config_sha256),
        ])
        identity = OrderedDict((k, self.versions[k]) for k in
                               ("dsl_version", "dsl_sha256", "ingest_config_sha256"))
        self.checkpoints = checkpoints.Checkpoints(
            program.name, args.fingerprint, identity, state_dir=args.state_dir,
            resume=args.resume, granularity=args.granularity, track=args.meta_out is not None)
        return self.checkpoints

    def finish(self, program, params, nulls, window, result, log, rows_read, watermarks,
               source_names):
        args = self.args
        _write(args.out, output.render(result))
        completed = _utc_now()
        run_id = str(uuid.uuid4())
        if args.meta_out is not None:
            units = self.checkpoints.units
            run = OrderedDict([
                ("run_id", run_id),
                ("started_at", _iso(self.started)),
                ("completed_at", _iso(completed)),
                ("duration_ms", int(round((time.monotonic() - self.clock) * 1000))),
                ("resume", bool(args.resume)),
            ])
            options = {"tz": args.tz, "timestamp_format": args.timestamp_format,
                       "null_markers": nulls}
            document = metadata.build(
                run, self.versions, units,
                metadata.file_statistics(units, rows_read, log.records), source_names,
                params, options, program, window, self.udfs, args.strict, log.records, result)
            try:
                checkpoints.write_atomic(args.meta_out,
                                         metadata.render(document).encode("utf-8"))
            except OSError as exc:
                raise InputError("cannot write metadata %r: %s"
                                 % (args.meta_out, exc.strerror or exc))
        marks = {name: (None if value is None else timestamps.format_utc(value))
                 for name, value in watermarks.items()}
        self.checkpoints.commit(run_id, _iso(self.started), _iso(completed), marks)
        uses_part5 = args.meta_out is not None or args.state_dir is not None
        message = versioning.warning(self.version, uses_part5)
        if message:
            warn("version", message, sys.stderr)


def run(argv):
    args = _parse_args(argv)
    if args.resume and args.state_dir is None:
        raise ArtifactError("--resume requires --state-dir")
    dsl_bytes, dsl_text = _read_dsl(args.dsl)
    version, dsl_text = versioning.read_header(dsl_text)
    context = _Run(args, dsl_bytes, version)
    if args.ingest_config is not None:
        return _run_ingest(context, dsl_text)
    if not args.specs:
        if _binds_sources(context, dsl_text):
            raise ConfigError("--ingest-config is required for a pipeline with sources { }")
        raise InputError("invalid arguments: --input is required")
    entries = inputs.resolve(args.specs, args.recursive, args.format)
    ts_parser = TimestampParser(args.tz, args.timestamp_format)
    nulls = sources.parse_null_markers(args.nulls)
    program = context.parse(dsl_text)
    if program.sources is not None:
        raise ConfigError("--ingest-config is required for a pipeline with sources { }")
    tracker = context.open_checkpoints(program, None)
    entries = [tracker.admit(checkpoints.DEFAULT_SOURCE, e) for e in entries]
    tables = sources.load(entries)
    schema = declarations.resolve_schema(program)
    params = declarations.bind_params(program, args.params, ts_parser)
    window = metadata.window_duration(program, params)
    dataset = sources.build_dataset(tables, ts_parser, nulls,
                                    schema.physical if schema is not None else None)
    bad_records = BadRecordLog(args.strict)
    try:
        result = engine.execute(program, dataset, schema, params, ts_parser, bad_records)
    finally:
        bad_records.write(args.bad_records_out)
    rows_read = {t.path: t.rows_read for t in tables}
    watermarks = {checkpoints.DEFAULT_SOURCE: _max_timestamp(dataset)}
    context.finish(program, params, nulls, window, result, bad_records, rows_read, watermarks,
                   [checkpoints.DEFAULT_SOURCE])


def _binds_sources(context, dsl_text):
    try:
        return context.parse(dsl_text).sources is not None
    except MtlError:
        return False


def _max_timestamp(dataset):
    if not dataset.has("timestamp") or dataset.type_of("timestamp") != "timestamp":
        return None
    latest = None
    for entry in dataset.entries():
        if entry[0] == "row":
            value = entry[2].get("timestamp")
            if value is not None and (latest is None or value > latest):
                latest = value
    return latest


def _run_ingest(context, dsl_text):
    """Multi-source run: sources and their files come from the ingest config."""
    args = context.args
    program = context.parse(dsl_text)
    ts_parser = TimestampParser(args.tz, args.timestamp_format)
    nulls = sources.parse_null_markers(args.nulls)
    defaults = ingest.Defaults(args.tz, args.timestamp_format, nulls, args.format, args.recursive)
    specs = ingest.load_config(args.ingest_config, defaults)
    config_sha256 = _sha256_of_file(args.ingest_config)
    declarations.resolve_schema(program)
    params = declarations.bind_params(program, args.params, ts_parser)
    window = metadata.window_duration(program, params)
    tracker = context.open_checkpoints(program, config_sha256)
    bad_records = BadRecordLog(args.strict)
    try:
        dataset, schema, readers = joins.prepare(program, specs, params, ts_parser, bad_records,
                                                 admit=tracker.admit)
        result = engine.execute(program, dataset, schema, params, ts_parser, bad_records)
        for reader in readers.values():
            if not reader.loaded:
                reader.rows(bad_records)   # bound but never joined: still consumed
    finally:
        bad_records.write(args.bad_records_out)
    rows_read = {}
    for reader in readers.values():
        rows_read.update(reader.rows_read)
    watermarks = {name: reader.max_timestamp() for name, reader in readers.items()}
    context.finish(program, params, nulls, window, result, bad_records, rows_read, watermarks,
                   list(readers))


def main(argv=None):
    try:
        run(sys.argv[1:] if argv is None else argv)
    except MtlError as err:
        return report(err, sys.stderr)
    except RecursionError:
        return report(DslError("DSL nesting too deep"), sys.stderr)
    except Exception as exc:  # last-resort guard: never leak a traceback
        from mtl_core.errors import ExecutionError
        return report(ExecutionError("internal error: %s" % exc), sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
