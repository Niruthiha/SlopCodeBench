"""Command-line interface: argument parsing, stage orchestration and error reporting."""
import argparse
import sys

from . import casts, inputs, loader, output, params, pipeline
from .badrecords import BadRecordSink
from .errors import IOFailure, MTLError, RuntimeFailure
from .parser import parse_program
from .schema import resolve_all
from .timeutil import TimestampParser, resolve_timezone
from .typecheck import check_program, check_schema_calcs


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise IOFailure(f"invalid arguments: {message}")


def build_arg_parser():
    parser = _ArgumentParser(
        prog="mtl.py",
        description="Run an MTL pipeline over sales event files and emit JSON.",
    )
    parser.add_argument("--input", action="append", nargs="+", default=[], metavar="PATH",
                        help="input file, directory or glob (repeatable)")
    parser.add_argument("--csv", action="append", nargs="+", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--dsl", required=True, help="path to the DSL file, or '-' for STDIN")
    parser.add_argument("--out", default=None, help="output file (default: STDOUT)")
    parser.add_argument("--tz", default="UTC", help="IANA timezone for naive timestamps")
    parser.add_argument("--timestamp-format", dest="timestamp_format", default=None,
                        help="strptime format for CSV/TSV timestamps (default: ISO 8601)")
    parser.add_argument("--strict", action="store_true",
                        help="abort on the first bad record and reject undeclared --param values")
    parser.add_argument("--param", action="append", nargs="+", default=[], metavar="KEY=VALUE",
                        help="pipeline parameter value (repeatable; last one wins)")
    parser.add_argument("--recursive", action="store_true",
                        help="traverse subdirectories of directory inputs")
    parser.add_argument("--format", default=inputs.AUTO, type=str.lower,
                        choices=inputs.FORMATS,
                        help="format for files whose extension does not tell (default: auto)")
    parser.add_argument("--nulls", default=None,
                        help="comma-separated null markers (default: empty, null, NULL, NaN)")
    parser.add_argument("--bad-records-out", dest="bad_records_out", default=None,
                        help="write rejected rows as JSON Lines to this file")
    return parser


def run(argv):
    """Execute the CLI stages and write the JSON result."""
    args = build_arg_parser().parse_args(argv)
    patterns = [p for group in args.input + args.csv for p in group]
    if not patterns:
        raise IOFailure("invalid arguments: --input is required")
    if args.dsl == "-" and inputs.STDIN in patterns:
        raise IOFailure("--input and --dsl cannot both read from STDIN")
    try:
        tz = resolve_timezone(args.tz)
    except ValueError as exc:
        raise IOFailure(str(exc)) from exc

    ts_parser = TimestampParser(tz, args.timestamp_format)
    casts.set_timestamp_parser(ts_parser)
    cli_params = params.parse_cli_params(item for group in args.param for item in group)
    ctx = loader.LoadContext(ts_parser, loader.parse_null_markers(args.nulls), args.strict)
    sink = BadRecordSink(args.strict)

    program = parse_program(loader.read_text(args.dsl))
    try:
        if program.schema_name is None:
            # Bare statements: the input columns are the typing environment.
            sources = loader.open_sources(inputs.resolve(patterns, args.recursive, args.format))
            fields, lenient = loader.infer_fields(sources, ctx)
            row_schema = check_program(program, fields)
            records = loader.iter_rows(sources, fields, ctx, sink, lenient)
            buckets = pipeline.run(program, records, row_schema=row_schema, sink=sink)
        else:
            params.check_provided(program.params, cli_params, args.strict)
            schemas = resolve_all(program.schemas)
            param_values = params.resolve(program.params, cli_params, ts_parser)
            for resolved in schemas.values():
                check_schema_calcs(resolved, param_values)
            used = schemas[program.schema_name]
            row_schema = check_program(program, used.types, param_values)
            sources = loader.open_sources(inputs.resolve(patterns, args.recursive, args.format))
            records = loader.iter_rows(sources, used.physical, ctx, sink)
            buckets = pipeline.run(program, records, used.calc_order, row_schema, sink)
        text = output.serialize(output.build_document(program, buckets))
    finally:
        sink.write(args.bad_records_out)
    _write(text, args.out)


def _write(text, destination):
    if destination is None or destination == "-":
        sys.stdout.write(text)
        sys.stdout.flush()
        return
    try:
        with open(destination, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except OSError as exc:
        raise IOFailure(f"cannot write output '{destination}': {exc}") from exc


def main(argv=None):
    try:
        run(sys.argv[1:] if argv is None else argv)
    except MTLError as err:
        return _report(err)
    except RecursionError:
        return _report(RuntimeFailure("expression nesting too deep"))
    except (ArithmeticError, ValueError) as exc:
        return _report(RuntimeFailure(str(exc) or type(exc).__name__))
    return 0


def _report(err):
    sys.stderr.write(err.diagnostic() + "\n")
    return err.exit_code
