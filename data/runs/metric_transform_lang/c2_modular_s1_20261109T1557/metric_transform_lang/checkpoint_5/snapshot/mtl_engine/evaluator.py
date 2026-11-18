"""Row-level evaluation of type-checked expressions (nulls propagate SQL-style).

Post-aggregation expressions are evaluated with a frame: the ordered list of
output rows and the current index, which lag()/lead() navigate.
"""
import math
import operator

from . import casts, dtypes, functions, udfs
from .ast_nodes import Binary, Call, Cast, ColumnRef, InExpr, Literal, Unary
from .errors import RuntimeFailure

_COMPARE = {
    "<": operator.lt, "<=": operator.le, ">": operator.gt,
    ">=": operator.ge, "==": operator.eq, "!=": operator.ne,
}


def evaluate(expr, row, frame=None):
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, ColumnRef):
        return row[expr.name]
    if isinstance(expr, Binary):
        return _eval_binary(expr, row, frame)
    if isinstance(expr, Unary):
        value = evaluate(expr.operand, row, frame)
        if value is None:
            return None
        if expr.op == "!":
            return not value
        return -value if expr.op == "-" else value
    if isinstance(expr, InExpr):
        haystack = evaluate(expr.haystack, row, frame)
        if haystack is None:
            return None
        return evaluate(expr.needle, row, frame) in haystack
    if isinstance(expr, Cast):
        value = evaluate(expr.operand, row, frame)
        return casts.convert(value, expr.operand.type, expr.target, expr.line)
    if isinstance(expr, Call):
        return _check_finite(_eval_call(expr, row, frame), expr)
    raise AssertionError(f"unknown expression node {expr!r}")


def _eval_call(expr, row, frame):
    name = expr.name
    if name == "param":
        return expr.value
    if name == "coalesce":
        value = evaluate(expr.args[0], row, frame)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return evaluate(expr.args[1], row, frame)
        return value
    if name in functions.WINDOW_FUNCTIONS:
        return _eval_offset(expr, row, frame)
    args = [evaluate(a, row, frame) for a in expr.args]
    udf = udfs.REGISTRY.get(name)
    if udf is not None:
        return udfs.call(udf, args, expr.line)
    return functions.call(name, args)


def _eval_offset(expr, row, frame):
    """lag(expr, k) / lead(expr, k): the value of expr k rows before/after this one."""
    k = evaluate(expr.args[1], row, frame)
    if k is None or k <= 0:
        raise RuntimeFailure(f"line {expr.line}: {expr.name}() offset must be a positive "
                             f"integer, got {k}")
    rows, index = frame
    target = index - k if expr.name == "lag" else index + k
    if not 0 <= target < len(rows):
        return None
    return evaluate(expr.args[0], rows[target], (rows, target))


def _eval_binary(expr, row, frame):
    op = expr.op
    if op == "&":
        left = evaluate(expr.left, row, frame)
        if left is False:
            return False
        right = evaluate(expr.right, row, frame)
        if right is False:
            return False
        return None if left is None or right is None else True
    if op == "|":
        left = evaluate(expr.left, row, frame)
        if left is True:
            return True
        right = evaluate(expr.right, row, frame)
        if right is True:
            return True
        return None if left is None or right is None else False

    left = evaluate(expr.left, row, frame)
    right = evaluate(expr.right, row, frame)
    if left is None or right is None:
        return None
    if op in _COMPARE:
        return _COMPARE[op](left, right)
    return _check_finite(_arithmetic(op, left, right, expr), expr)


def _arithmetic(op, left, right, expr):
    try:
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if right == 0:
            raise RuntimeFailure(f"line {expr.line}: division by zero")
        if op == "/":
            return left / right
        return left % right
    except OverflowError as exc:
        raise RuntimeFailure(f"line {expr.line}: numeric overflow") from exc


def _check_finite(value, expr):
    if isinstance(value, float) and not math.isfinite(value):
        raise RuntimeFailure(f"line {expr.line}: expression produced a non-finite number")
    if expr.type == dtypes.FLOAT and isinstance(value, int) and not isinstance(value, bool):
        try:
            return float(value)
        except OverflowError as exc:
            raise RuntimeFailure(f"line {expr.line}: numeric overflow") from exc
    return value
