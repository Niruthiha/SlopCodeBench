#!/usr/bin/env python3
"""MTL: roll up sales events (CSV, TSV, Parquet) according to a small pipeline DSL.

    python mtl.py --input <path-or-glob> [--input <path-or-glob> ...]
                  --dsl <path-or-> [--out <path-or-stdout>]
                  [--tz <IANA>] [--timestamp-format <str>] [--strict]
                  [--param key=value ...] [--recursive]
                  [--format <csv|tsv|parquet|auto>] [--nulls "<markers>"]
                  [--bad-records-out <path>]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mtl_core import declarations, engine, inputs, output, sources  # noqa: E402
from mtl_core.dsl_parser import parse_program  # noqa: E402
from mtl_core.errors import DslError, InputError, MtlError, report  # noqa: E402
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
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--format", dest="format", default=inputs.AUTO)
    parser.add_argument("--nulls", default=None)
    parser.add_argument("--bad-records-out", dest="bad_records_out", default=None)
    args = parser.parse_args(argv)
    args.format = args.format.strip().lower()
    if args.format not in inputs.FORMATS:
        raise InputError("invalid arguments: --format must be one of %s"
                         % ", ".join(inputs.FORMATS))
    args.specs = ([(p, None) for group in args.inputs for p in group]
                  + [(p, inputs.CSV) for group in args.csv_inputs for p in group])
    if not args.specs:
        raise InputError("invalid arguments: --input is required")
    pairs = [pair for group in args.params for pair in group]
    args.params = declarations.parse_cli_params(pairs)
    if args.params is None:
        raise InputError("invalid arguments: --param expects key=value")
    return args


def _read_dsl(source):
    try:
        if source == "-":
            data = sys.stdin.buffer.read()
        else:
            with open(source, "rb") as handle:
                data = handle.read()
    except OSError as exc:
        raise InputError("cannot read DSL %r: %s" % (source, exc.strerror or exc))
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("DSL %r is not valid UTF-8" % source)


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


def run(argv):
    args = _parse_args(argv)
    dsl_text = _read_dsl(args.dsl)
    tables = sources.load(inputs.resolve(args.specs, args.recursive, args.format))
    ts_parser = TimestampParser(args.tz, args.timestamp_format)
    nulls = sources.parse_null_markers(args.nulls)
    program = parse_program(dsl_text)
    schema = declarations.resolve_schema(program)
    params = declarations.bind_params(program, args.params, ts_parser)
    dataset = sources.build_dataset(tables, ts_parser, nulls,
                                    schema.physical if schema is not None else None)
    bad_records = BadRecordLog(args.strict)
    try:
        result = engine.execute(program, dataset, schema, params, ts_parser, bad_records)
    finally:
        bad_records.write(args.bad_records_out)
    _write(args.out, output.render(result))


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
