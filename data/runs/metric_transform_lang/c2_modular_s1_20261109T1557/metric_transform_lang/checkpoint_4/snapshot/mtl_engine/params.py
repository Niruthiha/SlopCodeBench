"""Pipeline parameters: merging DSL defaults with --param values into typed constants."""
from . import dtypes
from .errors import DSLSyntaxError, IOFailure, TypeCheckError


class ParamValue:
    def __init__(self, name, param_type, value):
        self.name = name
        self.type = param_type
        self.value = value


def parse_cli_params(items):
    """Turn ['key=value', ...] into a dict; the last duplicate wins."""
    values = {}
    for item in items:
        key, sep, value = item.partition("=")
        key = key.strip()
        if not sep or not key:
            raise IOFailure(f"invalid --param '{item}': expected key=value")
        values[key] = value
    return values


def check_provided(decls, cli_values, strict=False):
    """DSL errors: parameters without a default that were not supplied (and, in
    strict mode, supplied parameters the pipeline does not declare)."""
    missing = [d.name for d in decls if d.default is None and d.name not in cli_values]
    if missing:
        raise DSLSyntaxError(f"missing value for parameter(s) without default: "
                             f"{', '.join(missing)}")
    if strict:
        declared = {d.name for d in decls}
        unknown = sorted(k for k in cli_values if k not in declared)
        if unknown:
            raise DSLSyntaxError(f"undeclared parameter(s) supplied: {', '.join(unknown)}")


def resolve(decls, cli_values, ts_parser):
    """Return name -> ParamValue; values that do not fit their type are type errors."""
    resolved = {}
    for decl in decls:
        param_type = decl.type
        if param_type is None:
            param_type = decl.default.type if decl.default is not None else dtypes.STRING
        default = None
        if decl.default is not None:
            default = _from_literal(decl, param_type, ts_parser)
        if decl.name in cli_values:
            value = _from_text(decl.name, param_type, cli_values[decl.name], ts_parser)
        else:
            value = default
        resolved[decl.name] = ParamValue(decl.name, param_type, value)
    return resolved


def _from_literal(decl, param_type, ts_parser):
    lit = decl.default
    if lit.type == param_type:
        return lit.value
    if param_type == dtypes.FLOAT and lit.type == dtypes.INT:
        return float(lit.value)
    if param_type == dtypes.TIMESTAMP and lit.type == dtypes.STRING:
        try:
            return ts_parser.parse(lit.value)
        except ValueError as exc:
            raise TypeCheckError(f"line {decl.line}: default of parameter '{decl.name}' is not "
                                 f"a valid timestamp: {exc}") from exc
    raise TypeCheckError(f"line {decl.line}: default of parameter '{decl.name}' has type "
                         f"{lit.type}, expected {param_type}")


def _from_text(name, param_type, text, ts_parser):
    if param_type == dtypes.STRING:
        return text
    try:
        if param_type == dtypes.TIMESTAMP:
            return ts_parser.parse(text)
        return dtypes.parse_text(text.strip(), param_type)
    except ValueError as exc:
        raise TypeCheckError(f"--param {name}={text!r} is not a valid {param_type}: "
                             f"{exc}") from exc
