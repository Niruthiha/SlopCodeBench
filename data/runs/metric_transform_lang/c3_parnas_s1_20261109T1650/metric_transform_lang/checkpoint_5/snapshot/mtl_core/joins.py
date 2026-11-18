"""Multi-source pipelines.

Secret: how configured sources are bound to DSL aliases, how alias-scoped
pre steps run, the static typing of join predicates and projections
(qualified and unqualified column resolution, the working-timestamp rule),
and the join algorithm (hash join on equality conjuncts, temporal bands,
outer-join null padding, deterministic output order).  Callers get a
Dataset of the working relation that the ordinary pipeline consumes.
"""

import re
from collections import OrderedDict
from datetime import timedelta

from . import program as P
from . import quality as Q
from . import valuetypes as T
from .dataset import Dataset
from .declarations import resolve_schema
from .dsl_parser import WORKING_RELATION
from .errors import ConfigError, DslError, ExecutionError, TypeCheckError
from .expressions import coerce, column_references, compile_expression, is_assignable
from .ingest import SourceReader, assign_files

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_ROW_FAILURES = (ExecutionError, TypeCheckError, ArithmeticError, ValueError)


def prepare(program, specs, params, ts_parser, log, admit=None):
    """(dataset, schema_def, readers) of the working relation for engine.execute.

    readers: name -> SourceReader of the sources the pipeline reads.
    admit:   optional (source name, InputFile) -> InputFile hook applied to
             every file of those sources before anything is read.

    Everything static (config/DSL consistency, typing of scoped steps, join
    predicates and projections) is checked here; files are only read when
    the dataset is iterated.
    """
    by_name = OrderedDict((spec.name, spec) for spec in specs)
    if program.sources is not None:
        for binding in program.sources:
            if binding.name not in by_name:
                raise ConfigError("pipeline binds source %r, which the ingest config does "
                                  "not define" % binding.name)
    readers = OrderedDict((spec.name, SourceReader(spec, program.schemas, program.schema_name,
                                                   None)) for spec in specs)
    if program.sources is None:
        used = OrderedDict(readers)
    else:
        used = OrderedDict((b.name, readers[b.name]) for b in program.sources)
    for name, files in assign_files(specs).items():
        if name in used and admit is not None:
            files = [admit(name, entry) for entry in files]
        readers[name].files = files
    if program.sources is None:
        dataset, schema = _union(program, readers, log)
        return dataset, schema, used
    return _joined(program, readers, params, ts_parser, log), None, used


# ---------------------------------------------------------------------------
# Single-relation pipelines over every configured source


def _union(program, readers, log):
    schema = resolve_schema(program)
    if schema is not None:
        types = OrderedDict(schema.physical)
    else:
        types = OrderedDict()
        for reader in readers.values():
            for name, value_type in reader.ensure_columns().items():
                current = types.get(name)
                if current is None or current == value_type:
                    types[name] = value_type
                elif {current, value_type} == {T.INT, T.FLOAT}:
                    types[name] = T.FLOAT
                else:
                    raise TypeCheckError("column %r is %s in one source and %s in another"
                                         % (name, current, value_type))
    plans = []
    for reader in readers.values():
        columns = reader.ensure_columns() if schema is None else reader.columns
        widen = []
        for name, value_type in types.items():
            source_type = columns.get(name)
            if source_type is None or source_type == value_type:
                continue
            if source_type == T.INT and value_type == T.FLOAT:
                widen.append(name)
                continue
            raise TypeCheckError("source %r column %r is %s but the pipeline schema declares %s"
                                 % (reader.spec.name, name, source_type, value_type))
        plans.append((reader, widen))
    names = list(types)

    def entries():
        for reader, widen in plans:
            for prov, values in reader.rows(log):
                row = {n: values.get(n) for n in names}
                for n in widen:
                    if row[n] is not None:
                        row[n] = float(row[n])
                yield ("row", prov, row)

    return Dataset(names, [types[n] for n in names], entries), schema


# ---------------------------------------------------------------------------
# Joined pipelines


class _Relation:
    """Static column types plus a memoised producer of (provenance, values) rows."""

    def __init__(self, columns, produce):
        self.columns = columns
        self._produce = produce
        self._rows = None

    def rows(self):
        if self._rows is None:
            self._rows = self._produce()
        return self._rows


def _joined(program, readers, params, ts_parser, log):
    relations = {}
    for binding in program.sources:
        reader = readers[binding.name]
        blocks = [b for b in program.scoped if b.alias == binding.alias]
        relations[binding.alias] = _scoped_relation(binding.alias, reader, blocks, params, log)
    current = None
    for join in program.joins:
        left = current if join.left == WORKING_RELATION else relations[join.left]
        right = current if join.right == WORKING_RELATION else relations[join.right]
        current = _join_relation(join, left, right, params, ts_parser, log)
        if join.alias is not None:
            relations[join.alias] = current
    final = current
    names = list(final.columns)

    def entries():
        for prov, values in final.rows():
            yield ("row", prov, dict(values))

    return Dataset(names, [final.columns[n] for n in names], entries)


class _Scope:
    """Name resolution for expressions over one aliased relation."""

    def __init__(self, alias, columns):
        self.alias = alias
        self.columns = columns
        self.prefix = alias + "."

    def _column(self, name):
        return name[len(self.prefix):] if name.startswith(self.prefix) else name

    def has(self, name):
        return self._column(name) in self.columns

    def type_of(self, name):
        return self.columns[self._column(name)]


class _ScopedRecord:
    __slots__ = ("data", "prefix")

    def __init__(self, data, prefix):
        self.data = data
        self.prefix = prefix

    def get(self, name):
        if name.startswith(self.prefix):
            name = name[len(self.prefix):]
        return self.data.get(name)


def _scoped_relation(alias, reader, blocks, params, log):
    columns = OrderedDict(reader.ensure_columns())
    scope = _Scope(alias, columns)
    ts_parser = reader.spec.ts_parser
    ops = []

    def unknown(name):
        return TypeCheckError("unknown column %r in with %s { }" % (name, alias))

    for block in blocks:
        for step in block.steps:
            if isinstance(step, P.Calc):
                if step.name in columns:
                    raise DslError("calculated field %r collides with an existing field of %s"
                                   % (step.name, alias))
                compiled = compile_expression(step.expression, scope, params, unknown=unknown,
                                              ts_parser=ts_parser)
                if not is_assignable(step.type, compiled.type):
                    raise TypeCheckError("calc %r is declared %s but its expression is %s"
                                         % (step.name, step.type, compiled.type))
                columns[step.name] = step.type
                ops.append(("derive", step.name, coerce(step.type, compiled)))
            elif isinstance(step, P.Filter):
                compiled = compile_expression(step.predicate, scope, params, unknown=unknown,
                                              ts_parser=ts_parser)
                if not T.is_bool(compiled.type):
                    raise TypeCheckError("filter expression must be boolean, got %s"
                                         % compiled.type)
                ops.append(("filter", None, compiled.evaluate))
            else:
                compiled = compile_expression(step.expression, scope, params, unknown=unknown,
                                              ts_parser=ts_parser)
                columns[step.column] = compiled.type
                ops.append(("derive", step.column, compiled.evaluate))

    def produce():
        rows = []
        prefix = alias + "."
        for prov, values in reader.rows(log):
            data = OrderedDict(values)
            record = _ScopedRecord(data, prefix)
            try:
                keep = True
                for kind, name, evaluate in ops:
                    if kind == "filter":
                        if evaluate(record) is not True:
                            keep = False
                            break
                    else:
                        data[name] = evaluate(record)
            except _ROW_FAILURES as exc:
                log.add(Q.BadRecord(prov, _classify(exc), str(exc), {"values": data}))
                continue
            if keep:
                rows.append((prov, data))
        return rows

    return _Relation(columns, produce)


def _classify(exc):
    return Q.TYPE_ERROR if isinstance(exc, TypeCheckError) else Q.RUNTIME_ERROR


class _PairScope:
    """Name resolution over a pair of relations: `L.col`, `R.col` or an unambiguous `col`."""

    def __init__(self, left_name, left, right_name, right):
        self.sides = (left, right)
        self.qualifiers = (left_name, right_name)
        self.resolve = {}
        for side, (name, columns) in enumerate(((left_name, left), (right_name, right))):
            for column in columns:
                self.resolve["%s.%s" % (name, column)] = (side, column)
        self.ambiguous = set(left).intersection(right)
        for side, (columns, other) in enumerate(((left, right), (right, left))):
            for column in columns:
                if column not in other:
                    self.resolve[column] = (side, column)

    def has(self, name):
        return name in self.resolve

    def type_of(self, name):
        side, column = self.resolve[name]
        return self.sides[side][column]

    def unknown(self, name):
        if name in self.ambiguous:
            return DslError("column %r exists on both sides of the join; qualify it as %s.%s or "
                            "%s.%s" % (name, self.qualifiers[0], name, self.qualifiers[1], name))
        if "." in name:
            qualifier = name.split(".", 1)[0]
            if qualifier not in self.qualifiers:
                return DslError("%r does not name a side of this join (expected %s or %s)"
                                % (qualifier, self.qualifiers[0], self.qualifiers[1]))
        return TypeCheckError("unknown column %r in join" % name)

    def sides_of(self, expr):
        return {self.resolve[n][0] for n in column_references(expr) if n in self.resolve}


class _PairRecord:
    __slots__ = ("left", "right", "resolve")

    def __init__(self, left, right, resolve):
        self.left = left
        self.right = right
        self.resolve = resolve

    def get(self, name):
        side, column = self.resolve[name]
        data = self.left if side == 0 else self.right
        return None if data is None else data.get(column)


def _conjuncts(expr):
    if isinstance(expr, P.Binary) and expr.op == "&":
        return _conjuncts(expr.left) + _conjuncts(expr.right)
    return [expr]


def _band(join, left, right, params):
    spec = join.within
    for side, relation in zip((join.left, join.right), (left, right)):
        if "timestamp" not in relation.columns:
            raise DslError("line %d: join within %s requires a timestamp on both sides, but %r "
                           "has none" % (join.line, _describe(spec), side))
        if not T.is_timestamp(relation.columns["timestamp"]):
            raise TypeCheckError("join within requires %r.timestamp to be a timestamp, got %s"
                                 % (side, relation.columns["timestamp"]))
    if spec.param is None:
        return timedelta(seconds=spec.amount * _UNIT_SECONDS[spec.unit])
    if spec.param not in params:
        raise DslError("unknown parameter %r" % spec.param)
    value_type, value = params[spec.param]
    m = re.match(r"^\s*(\d+)\s*([smhd])\s*$", value) if T.is_string(value_type) else None
    if not m:
        raise TypeCheckError("within parameter %r must be a duration like '10m', got %r"
                             % (spec.param, value))
    return timedelta(seconds=int(m.group(1)) * _UNIT_SECONDS[m.group(2)])


def _describe(spec):
    if spec.param is not None:
        return "param(%r)" % spec.param
    return "%d%s" % (spec.amount, spec.unit)


def _join_relation(join, left, right, params, ts_parser, log):
    scope = _PairScope(join.left, left.columns, join.right, right.columns)

    def compile_pair(expr):
        return compile_expression(expr, scope, params, unknown=scope.unknown,
                                  ts_parser=ts_parser)

    on = compile_pair(join.on)
    if not T.is_bool(on.type):
        raise TypeCheckError("join on predicate must be boolean, got %s" % on.type)
    band = _band(join, left, right, params) if join.within is not None else None

    keys = []
    for conjunct in _conjuncts(join.on):
        if not (isinstance(conjunct, P.Binary) and conjunct.op == "=="):
            continue
        a, b = scope.sides_of(conjunct.left), scope.sides_of(conjunct.right)
        if a == {0} and b == {1}:
            keys.append((compile_pair(conjunct.left).evaluate,
                         compile_pair(conjunct.right).evaluate))
        elif a == {1} and b == {0}:
            keys.append((compile_pair(conjunct.right).evaluate,
                         compile_pair(conjunct.left).evaluate))

    columns = OrderedDict()
    project = []
    for item in join.project:
        compiled = compile_pair(item.expression)
        columns[item.name] = compiled.type
        project.append((item.name, compiled.evaluate))
    if "timestamp" in columns:
        if not T.is_timestamp(columns["timestamp"]):
            raise TypeCheckError("projected timestamp must be a timestamp, got %s"
                                 % columns["timestamp"])
    else:
        lt, rt = left.columns.get("timestamp"), right.columns.get("timestamp")
        if lt is not None and rt is not None:
            raise TypeCheckError("line %d: both %r and %r have a timestamp; project must say "
                                 "which one is the working timestamp" % (join.line, join.left,
                                                                         join.right))
        if lt is None:
            raise TypeCheckError("line %d: project defines no timestamp and %r has none to "
                                 "default to" % (join.line, join.left))
        if not T.is_timestamp(lt):
            raise TypeCheckError("%r.timestamp is %s, not a timestamp" % (join.left, lt))
        columns["timestamp"] = lt
        project.append(("timestamp", compile_pair(
            P.ColumnRef("%s.timestamp" % join.left)).evaluate))

    resolve = scope.resolve
    kind = join.kind

    def produce():
        lrows, rrows = left.rows(), right.rows()
        out = []

        def emit(prov, l, r):
            record = _PairRecord(l, r, resolve)
            values = OrderedDict()
            try:
                for name, evaluate in project:
                    values[name] = evaluate(record)
            except _ROW_FAILURES as exc:
                log.add(Q.BadRecord(prov, _classify(exc), "join projection: %s" % exc,
                                    {"left": l, "right": r}))
                return
            out.append((prov, values))

        index = None
        if keys:
            index = {}
            for j, (_, r) in enumerate(rrows):
                key = _key(keys, 1, _PairRecord(None, r, resolve))
                if key is not None:
                    index.setdefault(key, []).append(j)
        matched = [False] * len(rrows)
        for prov, l in lrows:
            if index is not None:
                key = _key(keys, 0, _PairRecord(l, None, resolve))
                candidates = index.get(key, ()) if key is not None else ()
            else:
                candidates = range(len(rrows))
            found = False
            for j in candidates:
                rprov, r = rrows[j]
                if band is not None and not _within(l, r, band):
                    continue
                try:
                    hit = on.evaluate(_PairRecord(l, r, resolve)) is True
                except _ROW_FAILURES as exc:
                    log.add(Q.BadRecord(prov, _classify(exc), "join predicate: %s" % exc,
                                        {"left": l, "right": r}))
                    continue
                if hit:
                    found = True
                    matched[j] = True
                    emit(prov, l, r)
            if not found and kind in ("left", "full"):
                emit(prov, l, None)
        if kind in ("right", "full"):
            for j, (rprov, r) in enumerate(rrows):
                if not matched[j]:
                    emit(rprov, None, r)
        return out

    return _Relation(columns, produce)


def _key(keys, side, record):
    values = []
    for pair in keys:
        try:
            value = pair[side](record)
        except _ROW_FAILURES:
            return None
        if value is None:
            return None
        values.append(value)
    return tuple(values)


def _within(l, r, band):
    a, b = l.get("timestamp"), r.get("timestamp")
    if a is None or b is None:
        return False
    return abs(a - b) <= band
