"""Static type checking of a parsed Program against the CSV schema."""
from . import dtypes, functions
from .ast_nodes import Apply, Binary, Call, ColumnRef, Filter, InExpr, Literal, Unary
from .errors import TypeCheckError

ARITHMETIC_OPS = ("+", "-", "*", "/", "%")
COMPARISON_OPS = ("<", "<=", ">", ">=", "==", "!=")
LOGICAL_OPS = ("&", "|")


def check_program(program, schema):
    """Annotate expression types and validate the pipeline; return the final schema."""
    schema = dict(schema)
    for op in program.row_ops:
        if isinstance(op, Filter):
            t = infer(op.predicate, schema)
            if t != dtypes.BOOL:
                raise TypeCheckError(f"line {op.line}: filter predicate must be boolean, got {t}")
        elif isinstance(op, Apply):
            schema[op.column] = infer(op.expr, schema)

    for col in program.group_columns:
        if col not in schema:
            raise TypeCheckError(f"line {program.group_by.line}: unknown group_by column '{col}'")

    if program.window is not None:
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
        if not dtypes.is_numeric(col_type):
            raise TypeCheckError(f"line {item.line}: {item.func}({item.column}) requires a numeric "
                                 f"column, got {col_type}")
    return schema


def infer(expr, schema):
    expr.type = _infer(expr, schema)
    return expr.type


def _infer(expr, schema):
    if isinstance(expr, Literal):
        return expr.type
    if isinstance(expr, ColumnRef):
        if expr.name not in schema:
            raise TypeCheckError(f"line {expr.line}: unknown column '{expr.name}'")
        return schema[expr.name]
    if isinstance(expr, Unary):
        t = infer(expr.operand, schema)
        if expr.op == "!":
            if t != dtypes.BOOL:
                raise TypeCheckError(f"line {expr.line}: '!' requires a boolean operand, got {t}")
            return dtypes.BOOL
        if not dtypes.is_numeric(t):
            raise TypeCheckError(f"line {expr.line}: unary '{expr.op}' requires a number, got {t}")
        return t
    if isinstance(expr, Binary):
        return _infer_binary(expr, schema)
    if isinstance(expr, InExpr):
        return _infer_in(expr, schema)
    if isinstance(expr, Call):
        arg_types = [infer(a, schema) for a in expr.args]
        return functions.result_type(expr.name, arg_types, expr.line)
    raise AssertionError(f"unknown expression node {expr!r}")


def _infer_binary(expr, schema):
    lt = infer(expr.left, schema)
    rt = infer(expr.right, schema)
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


def _infer_in(expr, schema):
    nt = infer(expr.needle, schema)
    ht = infer(expr.haystack, schema)
    if not (isinstance(expr.needle, Literal) and nt == dtypes.STRING):
        raise TypeCheckError(f"line {expr.line}: left side of 'in' must be a string literal")
    if not (isinstance(expr.haystack, ColumnRef) and ht == dtypes.STRING):
        raise TypeCheckError(f"line {expr.line}: right side of 'in' must be a string column")
    return dtypes.BOOL
