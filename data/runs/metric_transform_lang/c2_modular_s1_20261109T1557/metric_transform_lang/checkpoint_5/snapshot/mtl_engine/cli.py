"""Command-line interface: argument parsing, stage orchestration and error reporting."""
import argparse
import sys

from . import (casts, dtypes, ingest, inputs, joins, loader, metadata, output, params, pipeline,
               udfs, versions)
from .badrecords import BadRecordSink
from .errors import (ArtifactError, ConfigError, DSLSyntaxError, IOFailure, MTLError,
                     RuntimeFailure, TypeCheckError)
from .parser import parse_program
from .schema import resolve_all
from .state import DEFAULT_SOURCE, GRANULARITIES, MTIME_SIZE, SCHEMES, RunState, sha256_hex
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
    parser.add_argument("--meta-out", dest="meta_out", default=None,
                        help="write run metadata (provenance, stats, lineage) as JSON")
    parser.add_argument("--state-dir", dest="state_dir", default=None,
                        help="directory holding the resumable run state")
    parser.add_argument("--resume", action="store_true",
                        help="resume from the state in --state-dir, skipping completed files")
    parser.add_argument("--fingerprint", default=MTIME_SIZE, type=str.lower, choices=SCHEMES,
                        help="how input files are identified in the state (default: mtime_size)")
    parser.add_argument("--checkpoint-granularity", dest="checkpoint_granularity",
                        default="file", type=str.lower, choices=GRANULARITIES,
                        help="checkpoint unit (files are always the committed unit)")
    parser.add_argument("--udf", action="append", nargs="+", default=[], metavar="PATH",
                        help="Python file registering user-defined functions (repeatable)")
    return parser


class _Run:
    """What one invocation read and produced, shared by both execution modes."""

    def __init__(self, args):
        self.args = args
        self.dsl_sha256 = None
        self.config_sha256 = None
        self.version = None
        self.state = None
        self.param_values = {}


def _read_bytes(path, what):
    try:
        if path == "-":
            return sys.stdin.buffer.read()
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise IOFailure(f"cannot read {what} '{path}': {exc}") from exc


def _load_program(ctx):
    """Read the DSL, check its version header, parse it and gate its constructs."""
    data = _read_bytes(ctx.args.dsl, "DSL")
    ctx.dsl_sha256 = sha256_hex(data)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IOFailure(f"cannot read '{ctx.args.dsl}': {exc}") from exc
    ctx.version, text = versions.split_header(text)
    program = parse_program(text)
    versions.check_features(program, ctx.version)
    return program


def _open_state(ctx, program):
    args = ctx.args
    ctx.state = RunState(program.name or DEFAULT_SOURCE, versions.show(ctx.version),
                         ctx.dsl_sha256, ctx.config_sha256, args.fingerprint,
                         args.state_dir, args.resume)
    return ctx.state


def _observe(state, source, records):
    """Pass (Origin, row) records through, tracking the source's event-time watermark."""
    latest = []
    for record in records:
        latest.append(record[1].get(loader.EVENT_TIME))
        if len(latest) >= 4096:
            state.observe_timestamps(source, latest)
            latest = []
        yield record
    state.observe_timestamps(source, latest)


def _finish(ctx, program, sink, text, document):
    """Write the results, then the metadata, and commit the state last."""
    args = ctx.args
    ctx.state.finish()
    sink.write(args.bad_records_out)
    _write(text, args.out)
    if args.meta_out is not None:
        meta = metadata.build(ctx.state, program, args, ctx.param_values,
                              loader.parse_null_markers(args.nulls), sink, document)
        _write(metadata.serialize(meta), args.meta_out)
    ctx.state.commit()
    warning = versions.older_minor_warning(ctx.version)
    if warning:
        sys.stderr.write(warning + "\n")


def run(argv):
    """Execute the CLI stages and write the JSON result."""
    args = build_arg_parser().parse_args(argv)
    if args.resume and args.state_dir is None:
        raise ArtifactError("--resume requires --state-dir")
    patterns = [p for group in args.input + args.csv for p in group]
    if args.dsl == "-" and inputs.STDIN in patterns:
        raise IOFailure("--input and --dsl cannot both read from STDIN")
    udfs.load([p for group in args.udf for p in group])
    run_ctx = _Run(args)
    program = _load_program(run_ctx)
    if args.ingest_config is not None or not patterns:
        return _run_ingest(run_ctx, program)
    ts_parser, cli_params = _setup(args)
    ctx = loader.LoadContext(ts_parser, loader.parse_null_markers(args.nulls), args.strict)
    sink = BadRecordSink(args.strict)

    if program.sources is not None:
        raise ConfigError("--ingest-config is required for pipelines with a sources block")
    try:
        files = inputs.resolve(patterns, args.recursive, args.format)
        if program.schema_name is None:
            # Bare statements: the input columns are the typing environment.
            state = _open_state(run_ctx, program)
            sources = [state.open(DEFAULT_SOURCE, f) for f in files]
            fields, lenient = loader.infer_fields(sources, ctx)
            row_schema = check_program(program, fields)
            records = loader.iter_rows(sources, fields, ctx, sink, lenient)
            records = _observe(state, DEFAULT_SOURCE, records)
            buckets = pipeline.run(program, records, row_schema=row_schema, sink=sink)
        else:
            params.check_provided(program.params, cli_params, args.strict)
            schemas = resolve_all(program.schemas)
            param_values = params.resolve(program.params, cli_params, ts_parser)
            run_ctx.param_values = param_values
            for resolved in schemas.values():
                check_schema_calcs(resolved, param_values)
            used = schemas[program.schema_name]
            row_schema = check_program(program, used.types, param_values)
            state = _open_state(run_ctx, program)
            sources = [state.open(DEFAULT_SOURCE, f) for f in files]
            records = loader.iter_rows(sources, used.physical, ctx, sink)
            records = _observe(state, DEFAULT_SOURCE, records)
            buckets = pipeline.run(program, records, used.calc_order, row_schema, sink)
        document = output.build_document(program, buckets)
        text = output.serialize(document)
    except BaseException:
        sink.write(args.bad_records_out)
        raise
    _finish(run_ctx, program, sink, text, document)


def _setup(args):
    try:
        tz = resolve_timezone(args.tz)
    except ValueError as exc:
        raise IOFailure(str(exc)) from exc
    ts_parser = TimestampParser(tz, args.timestamp_format)
    casts.set_timestamp_parser(ts_parser)
    cli_params = params.parse_cli_params(item for group in args.param for item in group)
    return ts_parser, cli_params


def _run_ingest(run_ctx, program):
    """Multi-source mode: sources declared by --ingest-config, combined by joins."""
    args = run_ctx.args
    ts_parser, cli_params = _setup(args)
    if args.ingest_config is None:
        if program.sources is not None:
            raise ConfigError("--ingest-config is required for pipelines with a sources block")
        raise IOFailure("invalid arguments: --input or --ingest-config is required")
    if program.schema_name is None:
        raise DSLSyntaxError("--ingest-config requires a pipeline block using a schema")
    config = ingest.load_config(args.ingest_config, args.recursive, args.format)
    run_ctx.config_sha256 = sha256_hex(_read_bytes(args.ingest_config, "ingest config"))
    cli_nulls = loader.parse_null_markers(args.nulls)
    sink = BadRecordSink(args.strict)

    params.check_provided(program.params, cli_params, args.strict)
    schemas = resolve_all(program.schemas)
    param_values = params.resolve(program.params, cli_params, ts_parser)
    run_ctx.param_values = param_values
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
    state = _open_state(run_ctx, program)
    try:
        loaded = {name: _load_source(config.sources[name], files[name], ts_parser, cli_nulls,
                                     args.strict, sink, state) for name in used}
        if program.sources is not None:
            records = joins.run(program, {alias: loaded[name]
                                          for alias, name in alias_names.items()}, sink)
        else:
            records = [(origin, {f: pipeline.coerce(row.get(f), t) for f, t in working.items()})
                       for name in used for origin, row in loaded[name]]
        buckets = pipeline.run(program, records, (), row_schema, sink)
        document = output.build_document(program, buckets)
        text = output.serialize(document)
    except BaseException:
        sink.write(args.bad_records_out)
        raise
    _finish(run_ctx, program, sink, text, document)


def _check_union(config, working):
    """Without a sources block every source feeds the pipeline's schema directly."""
    for source in config.sources.values():
        for name, t in source.resolved.types.items():
            want = working.get(name)
            if want is not None and not (want == t or (want == dtypes.FLOAT and t == dtypes.INT)):
                raise TypeCheckError(f"source '{source.name}' field '{name}' has type {t}, "
                                     f"but the pipeline schema requires {want}")


def _load_source(source, files, ts_parser, cli_nulls, strict, sink, state):
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
        opened = state.open(source.name, input_file)
        rows.extend(loader.iter_mapped_rows(opened, plan, ctx, sink))
    state.observe_timestamps(source.name, (row.get(loader.EVENT_TIME) for _, row in rows))
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
