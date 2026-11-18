"""Command-line interface: argument parsing, stage orchestration and error reporting."""
import argparse
import sys

from . import csv_loader, output, pipeline
from .errors import IOFailure, MTLError, RuntimeFailure
from .parser import parse_program
from .timeutil import TimestampParser, resolve_timezone
from .typecheck import check_program


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise IOFailure(f"invalid arguments: {message}")


def build_arg_parser():
    parser = _ArgumentParser(
        prog="mtl.py",
        description="Run an MTL pipeline over a CSV of sales events and emit JSON.",
    )
    parser.add_argument("--csv", required=True, help="path to the input CSV file")
    parser.add_argument("--dsl", required=True, help="path to the DSL file, or '-' for STDIN")
    parser.add_argument("--out", default=None, help="output file (default: STDOUT)")
    parser.add_argument("--tz", default="UTC", help="IANA timezone for naive timestamps")
    parser.add_argument("--timestamp-format", dest="timestamp_format", default=None,
                        help="strptime format for timestamps (default: ISO 8601)")
    return parser


def run(argv):
    """Execute the CLI stages and write the JSON result."""
    args = build_arg_parser().parse_args(argv)
    if args.csv == "-" and args.dsl == "-":
        raise IOFailure("--csv and --dsl cannot both read from STDIN")
    try:
        tz = resolve_timezone(args.tz)
    except ValueError as exc:
        raise IOFailure(str(exc)) from exc

    program = parse_program(csv_loader.read_text(args.dsl))
    table = csv_loader.load_csv(args.csv, TimestampParser(tz, args.timestamp_format))
    check_program(program, table.schema)
    buckets = pipeline.run(program, table.rows)
    text = output.serialize(output.build_document(program, buckets))
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
