"""Schema and parameter declarations.

Secret: how schema inheritance is resolved (field order, override rules,
cycle and forward-reference detection, evaluation order of calculated
fields) and how parameter values are bound from defaults and CLI text.
"""

import math
import re
from collections import OrderedDict, namedtuple

from . import valuetypes as T
from .errors import DslError, TypeCheckError
from .expressions import column_references, uses_row_relative

ResolvedSchema = namedtuple("ResolvedSchema", "name fields physical calcs")
# fields:   OrderedDict name -> FieldDef (final definition of every field)
# physical: OrderedDict name -> type of the fields read from the CSV
# calcs:    FieldDefs of calculated fields, in a dependency-respecting order

_INT_TEXT = re.compile(r"^\s*[+-]?\d+\s*$")
_FLOAT_TEXT = re.compile(r"^\s*[+-]?(\d+\.?\d*([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?)\s*$")


def _legal_override(old, new):
    return old == new or (old == T.INT and new == T.FLOAT)


def resolve_schema(program):
    """Resolve the schema named by the pipeline's `using`; None for bare programs."""
    if program.schema_name is None:
        return None
    return resolve_named_schema(program.schemas, program.schema_name)


def resolve_named_schema(schemas, schema_name):
    """Resolve schema `schema_name` (with its inheritance chain) from `schemas`."""
    chain = []
    seen = set()
    name = schema_name
    while name is not None:
        if name in seen:
            raise DslError("circular schema inheritance involving %r" % name)
        if name not in schemas:
            raise DslError("schema %r extends unknown schema %r" % (chain[-1].name, name))
        seen.add(name)
        chain.append(schemas[name])
        name = schemas[name].base
    _check_all_cycles(schemas)

    fields = OrderedDict()
    for schema in reversed(chain):
        for field in schema.fields:
            if field.expression is not None:
                if uses_row_relative(field.expression):
                    raise DslError("schema %r field %r: lag()/lead() are not allowed in schemas"
                                   % (schema.name, field.name))
                for ref in column_references(field.expression):
                    if ref not in fields:
                        raise DslError("schema %r field %r references unknown or later field %r"
                                       % (schema.name, field.name, ref))
            if field.name in fields:
                old = fields[field.name].type
                if not _legal_override(old, field.type):
                    raise TypeCheckError("schema %r cannot override field %r from %s to %s"
                                         % (schema.name, field.name, old, field.type))
            fields[field.name] = field

    physical = OrderedDict((f.name, f.type) for f in fields.values() if f.expression is None)
    return ResolvedSchema(schema_name, fields, physical, _calc_order(fields))


def _check_all_cycles(schemas):
    for start in schemas:
        seen = set()
        name = start
        while name is not None and name in schemas:
            if name in seen:
                raise DslError("circular schema inheritance involving %r" % name)
            seen.add(name)
            name = schemas[name].base
        if name is not None:
            raise DslError("schema %r extends unknown schema %r" % (start, name))


def _calc_order(fields):
    order = []
    state = {}

    def visit(name):
        if state.get(name) == "done":
            return
        if state.get(name) == "active":
            raise DslError("calculated field %r depends on itself" % name)
        state[name] = "active"
        field = fields[name]
        for ref in column_references(field.expression):
            if ref in fields and fields[ref].expression is not None:
                visit(ref)
        state[name] = "done"
        order.append(field)

    for name, field in fields.items():
        if field.expression is not None:
            visit(name)
    return order


def parse_cli_params(pairs):
    """Turn 'key=value' strings into a dict (last one wins); None on bad syntax."""
    values = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        key = key.strip()
        if not sep or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            return None
        values[key] = value
    return values


def bind_params(program, cli_values, ts_parser):
    """Return name -> (type, value) for every declared parameter.

    Bare programs (no pipeline block) expose CLI values as strings.
    """
    if program.name is None and not program.params:
        return {k: (T.STRING, v) for k, v in cli_values.items()}
    bound = {}
    for decl in program.params:
        value_type = decl.type
        default = decl.default
        if value_type is None:
            value_type = default.kind if default is not None else T.STRING
        if decl.name in cli_values:
            text = cli_values[decl.name]
            try:
                value = _parse_text(text, value_type, ts_parser)
            except (ValueError, OverflowError):
                raise TypeCheckError("parameter %r value %r is not a valid %s"
                                     % (decl.name, text, value_type))
        elif default is not None:
            value = _default_value(decl.name, default, value_type, ts_parser)
        else:
            raise DslError("parameter %r has no default and was not given with --param"
                           % decl.name)
        bound[decl.name] = (value_type, value)
    return bound


def _default_value(name, literal, value_type, ts_parser):
    kind, value = literal.kind, literal.value
    if kind == value_type:
        if isinstance(value, float) and not math.isfinite(value):
            raise TypeCheckError("parameter %r default is not finite" % name)
        return value
    if value_type == T.FLOAT and kind == T.INT:
        return float(value)
    if value_type == T.TIMESTAMP and kind == T.STRING:
        try:
            return ts_parser.parse(value)
        except (ValueError, OverflowError):
            pass
    raise TypeCheckError("parameter %r default %r is not a valid %s" % (name, value, value_type))


def _parse_text(text, value_type, ts_parser):
    if value_type == T.STRING:
        return text
    if value_type == T.INT:
        if not _INT_TEXT.match(text):
            raise ValueError(text)
        return int(text)
    if value_type == T.FLOAT:
        if not _FLOAT_TEXT.match(text):
            raise ValueError(text)
        value = float(text)
        if not math.isfinite(value):
            raise ValueError(text)
        return value
    if value_type == T.BOOL:
        lowered = text.strip().lower()
        if lowered not in ("true", "false"):
            raise ValueError(text)
        return lowered == "true"
    return ts_parser.parse(text)
