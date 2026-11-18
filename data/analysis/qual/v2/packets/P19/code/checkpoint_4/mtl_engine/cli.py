"""Command-line interface: argument parsing, stage orchestration and error reporting."""
import argparse
import sys

from . import casts, dtypes, ingest, inputs, joins, loader, output, params, pipeline
from .badrecords import BadRecordSink
from .errors import ConfigError, DSLSyntaxError, IOFailure, MTLError, RuntimeFailure, TypeCheckError
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
    parser.add_argument("--ingest-config", dest="ingest_config", default=None,
                        help="YAML/JSON config declaring the named input sources")
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
    if args.ingest_config is not None or not patterns:
        return _run_ingest(args)
    if args.dsl == "-" and inputs.STDIN in patterns:
        raise IOFailure("--input and --dsl cannot both read from STDIN")
    ts_parser, cli_params = _setup(args)
    ctx = loader.LoadContext(ts_parser, loader.parse_null_markers(args.nulls), args.strict)
    sink = BadRecordSink(args.strict)

    program = parse_program(loader.read_text(args.dsl))
    if program.sources is not None:
        raise ConfigError("--ingest-config is required for pipelines with a sources block")
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


def _setup(args):
    try:
        tz = resolve_timezone(args.tz)
    except ValueError as exc:
        raise IOFailure(str(exc)) from exc
    ts_parser = TimestampParser(tz, args.timestamp_format)
    casts.set_timestamp_parser(ts_parser)
    cli_params = params.parse_cli_params(item for group in args.param for item in group)
    return ts_parser, cli_params


def _run_ingest(args):
    """Multi-source mode: sources declared by --ingest-config, combined by joins."""
    ts_parser, cli_params = _setup(args)
    program = parse_program(loader.read_text(args.dsl))
    if args.ingest_config is None:
        if program.sources is not None:
            raise ConfigError("--ingest-config is required for pipelines with a sources block")
        raise IOFailure("invalid arguments: --input or --ingest-config is required")
    if program.schema_name is None:
        raise DSLSyntaxError("--ingest-config requires a pipeline block using a schema")
    config = ingest.load_config(args.ingest_config, args.recursive, args.format)
    cli_nulls = loader.parse_null_markers(args.nulls)
    sink = BadRecordSink(args.strict)

    params.check_provided(program.params, cli_params, args.strict)
    schemas = resolve_all(program.schemas)
    param_values = params.resolve(program.params, cli_params, ts_parser)
    for resolved in schemas.values():
        check_schema_calcs(resolved, param_values)
    ingest.bind_schemas(config, schemas, program.schema_name, ts_parser)

    if program.sources is not None:
        alias_names = {}
        for binding in program.sources.bindings:
            if binding.name not in config.sources:
                raise ConfigError(f"line {binding.line}: source '{binding.name}' is not "
                                  "declared in the ingest config")
            alias_names[binding.alias] = binding.name
        alias_types = {alias: config.sources[name].resolved.types
                       for alias, name in alias_names.items()}
        working = joins.check(program, alias_types, param_values)
        used = list(dict.fromkeys(alias_names.values()))
    else:
        working = schemas[program.schema_name].types
        _check_union(config, working)
        used = list(config.sources)
    row_schema = check_program(program, working, param_values)

    files = ingest.assign_files(config, set(used))
    try:
        loaded = {name: _load_source(config.sources[name], files[name], ts_parser, cli_nulls,
                                     args.strict, sink) for name in used}
        if program.sources is not None:
            records = joins.run(program, {alias: loaded[name]
                                          for alias, name in alias_names.items()}, sink)
        else:
            records = [(origin, {f: pipeline.coerce(row.get(f), t) for f, t in working.items()})
                       for name in used for origin, row in loaded[name]]
        buckets = pipeline.run(program, records, (), row_schema, sink)
        text = output.serialize(output.build_document(program, buckets))
    finally:
        sink.write(args.bad_records_out)
    _write(text, args.out)


def _check_union(config, working):
    """Without a sources block every source feeds the pipeline's schema directly."""
    for source in config.sources.values():
        for name, t in source.resolved.types.items():
            want = working.get(name)
            if want is not None and not (want == t or (want == dtypes.FLOAT and t == dtypes.INT)):
                raise TypeCheckError(f"source '{source.name}' field '{name}' has type {t}, "
                                     f"but the pipeline schema requires {want}")


def _load_source(source, files, ts_parser, cli_nulls, strict, sink):
    """Read, map and validate every file of one ingest source; returns (Origin, row) pairs
    with the schema's calculated fields evaluated."""
    tz = source.tz or ts_parser.default_tz
    parser = TimestampParser(tz, source.timestamp_format or ts_parser.fmt)
    nulls = source.nulls if source.nulls is not None else cli_nulls
    ctx = loader.LoadContext(parser, nulls, strict)
    resolved = source.resolved
    mapping = source.mapping
    fields = []
    for name, ftype in resolved.physical.items():
        has_default = name in source.default_values
        fields.append(loader.FieldPlan(name, ftype, mapping.cast.get(name),
                                       source.default_values.get(name), has_default))
    required = list(source.required_fields)
    if resolved.physical.get(loader.EVENT_TIME) == dtypes.TIMESTAMP \
            and loader.EVENT_TIME not in required:
        required.append(loader.EVENT_TIME)
    plan = loader.SourcePlan(fields, mapping.rename, mapping.drop, required)

    rows = []
    for input_file in files:
        opened = loader.open_source(input_file)
        rows.extend(loader.iter_mapped_rows(opened, plan, ctx, sink))
    calcs = [(f.name, f.expr, f.type) for f in resolved.calc_order]
    if calcs:
        rows = pipeline.transform_rows(rows, calcs, (), sink)
    return rows


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
