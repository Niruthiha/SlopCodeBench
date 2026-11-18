"""Static type checking of a parsed Program against its typing environment.

Name problems that are structural (forward references, aggregate aliases in
pre-stage calcs, undeclared parameters, lag/lead outside post-aggregation)
are reported as DSL errors before an expression is typed; everything else
is a type error.
"""
from . import casts, dtypes, functions
from .ast_nodes import (Apply, Binary, Call, Cast, ColumnRef, Filter, InExpr, Literal,
                        Unary)
from .errors import DSLSyntaxError, TypeCheckError
from .lexer import DURATION_UNITS

ARITHMETIC_OPS = ("+", "-", "*", "/", "%")
COMPARISON_OPS = ("<", "<=", ">", ">=", "==", "!=")
LOGICAL_OPS = ("&", "|")
WINDOW_COLUMNS = ("window_start", "window_end")

_AGG_TYPES = {"count": dtypes.INT, "average": dtypes.FLOAT, "median": dtypes.FLOAT,
              "std": dtypes.FLOAT, "var": dtypes.FLOAT}


def check_program(program, schema, params=None):
    """Annotate expression types and validate the pipeline; return the final row schema.

    `schema` maps the input fields to their types; `params` maps declared
    parameter names to resolved ParamValues.
    """
    params = params or {}
    schema = dict(schema)
    aliases = {item.alias for item in program.aggregate.items}

    pre_calcs = program.pre_calcs
    for idx, calc in enumerate(pre_calcs):
        if calc.name in schema:
            raise DSLSyntaxError(f"line {calc.line}: calc '{calc.name}' collides with an "
                                 "existing field")
        check_names(calc.expr, schema, params, line=calc.line,
                    aliases=aliases, later={c.name for c in pre_calcs[idx + 1:]})
        check_declared(calc.name, calc.declared_type, infer(calc.expr, schema, params), calc.line)
        schema[calc.name] = calc.declared_type

    for op in program.row_ops:
        if isinstance(op, Filter):
            check_names(op.predicate, schema, params, line=op.line)
            t = infer(op.predicate, schema, params)
            if t != dtypes.BOOL:
                raise TypeCheckError(f"line {op.line}: filter predicate must be boolean, got {t}")
        elif isinstance(op, Apply):
            check_names(op.expr, schema, params, line=op.line)
            schema[op.column] = infer(op.expr, schema, params)

    for col in program.group_columns:
        if col not in schema:
            raise TypeCheckError(f"line {program.group_by.line}: unknown group_by column '{col}'")

    if program.window is not None:
        _resolve_window_param(program.window, params)
        ts_type = schema.get("timestamp")
        if ts_type != dtypes.TIMESTAMP:
            raise TypeCheckError(f"line {program.window.line}: window requires a 'timestamp' "
                                 f"column of type timestamp, got {ts_type}")

    for item in program.aggregate.items:
        if item.column is None:
            if item.func != "count":
                raise TypeCheckError(f"line {item.line}: {item.func}(*) is not allowed; "
                                     "only count(*) may use '*'")
            continue
        if item.column not in schema:
            raise TypeCheckError(f"line {item.line}: unknown column '{item.column}' in {item.func}()")
        col_type = schema[item.column]
        if item.func != "count" and not dtypes.is_numeric(col_type):
            raise TypeCheckError(f"line {item.line}: {item.func}({item.column}) requires a numeric "
                                 f"column, got {col_type}")

    output = output_schema(program, schema)
    post_calcs = program.post_calcs
    for idx, calc in enumerate(post_calcs):
        check_names(calc.expr, output, params, line=calc.line, allow_window=True,
                    later={c.name for c in post_calcs[idx + 1:]})
        check_declared(calc.name, calc.declared_type, infer(calc.expr, output, params), calc.line)
        output[calc.name] = calc.declared_type
    return schema


def output_schema(program, schema):
    """Types of the fields of an aggregated output row (before post-agg calcs)."""
    output = {}
    if program.window is not None:
        for col in WINDOW_COLUMNS:
            output[col] = dtypes.TIMESTAMP
    for col in program.group_columns:
        output[col] = schema[col]
    for item in program.aggregate.items:
        output[item.alias] = _AGG_TYPES.get(item.func) or schema[item.column]
    return output


def check_schema_calcs(resolved, params):
    """Type the calculated fields of a resolved schema against its own fields."""
    types = resolved.types
    for field in resolved.calc_order:
        check_names(field.expr, field.visible, params, line=field.line)
        check_declared(field.name, field.type, infer(field.expr, types, params), field.line)


def check_declared(name, declared, inferred, line):
    if not (declared == inferred or (declared == dtypes.FLOAT and inferred == dtypes.INT)):
        raise TypeCheckError(f"line {line}: '{name}' is declared {declared} but its "
                             f"expression has type {inferred}")


def _resolve_window_param(window, params):
    if window.param is None:
        return
    param = params.get(window.param)
    if param is None:
        raise DSLSyntaxError(f"line {window.line}: unknown parameter '{window.param}'")
    value = param.value
    if (param.type != dtypes.STRING or len(value) < 2 or not value[:-1].isdigit()
            or value[-1] not in DURATION_UNITS or int(value[:-1]) <= 0):
        raise TypeCheckError(f"line {window.line}: window parameter '{window.param}' must be a "
                             f"duration string like '1h', got {param.type} {value!r}")
    window.amount = int(value[:-1])
    window.unit = value[-1]
    window.seconds = window.amount * DURATION_UNITS[window.unit]


def walk(expr):
    """Yield every node of an expression tree (pre-order)."""
    stack = [expr]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, Unary):
            stack.append(node.operand)
        elif isinstance(node, Binary):
            stack.extend((node.right, node.left))
        elif isinstance(node, InExpr):
            stack.extend((node.haystack, node.needle))
        elif isinstance(node, Call):
            stack.extend(reversed(node.args))
        elif isinstance(node, Cast):
            stack.append(node.operand)


def check_names(expr, visible, params, line, aliases=(), later=(), allow_window=False):
    """Report structural name errors; unknown plain columns are left to `infer`."""
    for node in walk(expr):
        if isinstance(node, ColumnRef) and node.name not in visible:
            if node.name in later:
                raise DSLSyntaxError(f"line {line}: '{node.name}' is referenced before "
                                     "it is declared")
            if node.name in aliases:
                raise DSLSyntaxError(f"line {line}: aggregate alias '{node.name}' cannot be "
                                     "used before aggregation")
        elif isinstance(node, Call):
            if node.name == "param" and node.args[0].value not in params:
                raise DSLSyntaxError(f"line {line}: unknown parameter '{node.args[0].value}'")
            if node.name in functions.WINDOW_FUNCTIONS and not allow_window:
                raise DSLSyntaxError(f"line {line}: {node.name}() is only allowed in "
                                     "@stage(post_agg) calcs")


def infer(expr, schema, params=None):
    expr.type = _infer(expr, schema, params or {})
    return expr.type


def _infer(expr, schema, params):
    if isinstance(expr, Literal):
        return expr.type
    if isinstance(expr, ColumnRef):
        if expr.name not in schema:
            raise TypeCheckError(f"line {expr.line}: unknown column '{expr.name}'")
        return schema[expr.name]
    if isinstance(expr, Unary):
        t = infer(expr.operand, schema, params)
        if expr.op == "!":
            if t != dtypes.BOOL:
                raise TypeCheckError(f"line {expr.line}: '!' requires a boolean operand, got {t}")
            return dtypes.BOOL
        if not dtypes.is_numeric(t):
            raise TypeCheckError(f"line {expr.line}: unary '{expr.op}' requires a number, got {t}")
        return t
    if isinstance(expr, Binary):
        return _infer_binary(expr, schema, params)
    if isinstance(expr, InExpr):
        return _infer_in(expr, schema, params)
    if isinstance(expr, Cast):
        source = infer(expr.operand, schema, params)
        if not casts.allowed(source, expr.target):
            raise TypeCheckError(f"line {expr.line}: cannot cast {source} to {expr.target}")
        return expr.target
    if isinstance(expr, Call):
        return _infer_call(expr, schema, params)
    raise AssertionError(f"unknown expression node {expr!r}")


def _infer_call(expr, schema, params):
    if expr.name == "param":
        name = expr.args[0].value
        if name not in params:
            raise DSLSyntaxError(f"line {expr.line}: unknown parameter '{name}'")
        expr.value = params[name].value
        return params[name].type
    arg_types = [infer(a, schema, params) for a in expr.args]
    if expr.name in functions.WINDOW_FUNCTIONS:
        if arg_types[1] != dtypes.INT:
            raise TypeCheckError(f"line {expr.line}: {expr.name}() offset must be an int, "
                                 f"got {arg_types[1]}")
        return arg_types[0]
    return functions.result_type(expr.name, arg_types, expr.line)


def _infer_binary(expr, schema, params):
    lt = infer(expr.left, schema, params)
    rt = infer(expr.right, schema, params)
    op = expr.op
    if op in LOGICAL_OPS:
        if lt != dtypes.BOOL or rt != dtypes.BOOL:
            raise TypeCheckError(f"line {expr.line}: '{op}' requires boolean operands, "
                                 f"got {lt} and {rt}")
        return dtypes.BOOL
    if op in COMPARISON_OPS:
        if not dtypes.comparable(lt, rt, op):
            raise TypeCheckError(f"line {expr.line}: cannot compare {lt} with {rt} using '{op}'")
        return dtypes.BOOL
    if op in ARITHMETIC_OPS:
        if not (dtypes.is_numeric(lt) and dtypes.is_numeric(rt)):
            raise TypeCheckError(f"line {expr.line}: '{op}' requires numeric operands, "
                                 f"got {lt} and {rt}")
        if op == "/":
            return dtypes.FLOAT
        return dtypes.numeric_result(lt, rt)
    raise AssertionError(f"unknown operator {op}")


def _infer_in(expr, schema, params):
    nt = infer(expr.needle, schema, params)
    ht = infer(expr.haystack, schema, params)
    if not (isinstance(expr.needle, Literal) and nt == dtypes.STRING):
        raise TypeCheckError(f"line {expr.line}: left side of 'in' must be a string literal")
    if not (isinstance(expr.haystack, ColumnRef) and ht == dtypes.STRING):
        raise TypeCheckError(f"line {expr.line}: right side of 'in' must be a string column")
    return dtypes.BOOL
