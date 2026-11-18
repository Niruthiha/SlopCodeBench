"""Row-level evaluation of type-checked expressions (nulls propagate SQL-style)."""
import math
import operator

from . import dtypes, functions
from .ast_nodes import Binary, Call, ColumnRef, InExpr, Literal, Unary
from .errors import RuntimeFailure

_COMPARE = {
    "<": operator.lt, "<=": operator.le, ">": operator.gt,
    ">=": operator.ge, "==": operator.eq, "!=": operator.ne,
}


def evaluate(expr, row):
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, ColumnRef):
        return row[expr.name]
    if isinstance(expr, Binary):
        return _eval_binary(expr, row)
    if isinstance(expr, Unary):
        value = evaluate(expr.operand, row)
        if value is None:
            return None
        if expr.op == "!":
            return not value
        return -value if expr.op == "-" else value
    if isinstance(expr, InExpr):
        haystack = evaluate(expr.haystack, row)
        if haystack is None:
            return None
        return evaluate(expr.needle, row) in haystack
    if isinstance(expr, Call):
        args = [evaluate(a, row) for a in expr.args]
        return _check_finite(functions.call(expr.name, args), expr)
    raise AssertionError(f"unknown expression node {expr!r}")


def _eval_binary(expr, row):
    op = expr.op
    if op == "&":
        left = evaluate(expr.left, row)
        if left is False:
            return False
        right = evaluate(expr.right, row)
        if right is False:
            return False
        return None if left is None or right is None else True
    if op == "|":
        left = evaluate(expr.left, row)
        if left is True:
            return True
        right = evaluate(expr.right, row)
        if right is True:
            return True
        return None if left is None or right is None else False

    left = evaluate(expr.left, row)
    right = evaluate(expr.right, row)
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
