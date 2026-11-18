"""Scalar and boolean expressions.

Secret: the static typing rules applied to expressions and transforms and
how they are evaluated -- null propagation, half-away-from-zero rounding,
and detection of arithmetic faults (division by zero, non-finite results).
"""

import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from . import program as P
from . import timestamps
from . import valuetypes as T
from .errors import DslError, ExecutionError, TypeCheckError

_ORDERING = ("<", "<=", ">", ">=")
_EQUALITY = ("==", "!=")
_ARITHMETIC = ("+", "-", "*", "/", "%")
_TRANSFORM_ARITY = {"len": (1, 1), "day": (1, 1), "month": (1, 1), "year": (1, 1), "round": (1, 2)}


class Compiled:
    """A type-checked expression: `.type` and `.evaluate(record)`."""

    def __init__(self, value_type, evaluate):
        self.type = value_type
        self.evaluate = evaluate


def compile_expression(expr, schema):
    """Type-check `expr` against `schema` (has/type_of) and return a Compiled."""
    return _Compiler(schema).compile(expr)


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ExecutionError("arithmetic produced a non-finite value")
    return value


def round_half_away(value, digits):
    if not math.isfinite(value):
        raise ExecutionError("cannot round a non-finite value")
    try:
        exact = Decimal(repr(float(value))) if isinstance(value, float) else Decimal(value)
        rounded = exact.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
        result = float(rounded)
    except (InvalidOperation, OverflowError):
        result = float(value)
    return _finite(result) + 0.0


class _Compiler:
    def __init__(self, schema):
        self.schema = schema

    def compile(self, expr):
        if isinstance(expr, P.Literal):
            return self.literal(expr)
        if isinstance(expr, P.ColumnRef):
            return self.column(expr.name)
        if isinstance(expr, P.Unary):
            return self.unary(expr)
        if isinstance(expr, P.Binary):
            return self.binary(expr)
        if isinstance(expr, P.Call):
            return self.call(expr)
        raise DslError("unsupported expression")

    def literal(self, expr):
        value_type = {"int": T.INT, "float": T.FLOAT, "string": T.STRING, "bool": T.BOOL}[expr.kind]
        value = expr.value
        if isinstance(value, float):
            _finite(value)
        return Compiled(value_type, lambda record: value)

    def column(self, name):
        if not self.schema.has(name):
            raise TypeCheckError("unknown column %r" % name)
        return Compiled(self.schema.type_of(name), lambda record: record.get(name))

    def unary(self, expr):
        inner = self.compile(expr.operand)
        ev = inner.evaluate
        if expr.op == "!":
            if not T.is_bool(inner.type):
                raise TypeCheckError("'!' requires a boolean operand, got %s" % T.type_name(inner.type))
            return Compiled(T.BOOL, lambda r: not (ev(r) is True))
        if not T.is_numeric(inner.type):
            raise TypeCheckError("unary '%s' requires a numeric operand, got %s"
                                 % (expr.op, T.type_name(inner.type)))
        if expr.op == "-":
            def negate(r):
                v = ev(r)
                return None if v is None else -v
            return Compiled(inner.type, negate)
        return inner

    def binary(self, expr):
        op = expr.op
        if op == "in":
            return self.membership(expr)
        left = self.compile(expr.left)
        right = self.compile(expr.right)
        lt, rt = left.type, right.type
        le, re_ = left.evaluate, right.evaluate
        if op in ("&", "|"):
            if not (T.is_bool(lt) and T.is_bool(rt)):
                raise TypeCheckError("'%s' requires boolean operands, got %s and %s"
                                     % (op, T.type_name(lt), T.type_name(rt)))
            if op == "&":
                return Compiled(T.BOOL, lambda r: le(r) is True and re_(r) is True)
            return Compiled(T.BOOL, lambda r: le(r) is True or re_(r) is True)
        if op in _EQUALITY or op in _ORDERING:
            allowed = T.can_order(lt, rt) if op in _ORDERING else T.can_compare(lt, rt)
            if not allowed:
                raise TypeCheckError("cannot compare %s %s %s"
                                     % (T.type_name(lt), op, T.type_name(rt)))
            return Compiled(T.BOOL, _comparison(op, le, re_))
        if op in _ARITHMETIC:
            if not (T.is_numeric(lt) and T.is_numeric(rt)):
                raise TypeCheckError("'%s' requires numeric operands, got %s and %s"
                                     % (op, T.type_name(lt), T.type_name(rt)))
            result_type = T.FLOAT if op == "/" else T.widen(lt, rt)
            return Compiled(result_type, _arithmetic(op, le, re_))
        raise DslError("unsupported operator %r" % op)

    def membership(self, expr):
        if not (isinstance(expr.left, P.Literal) and expr.left.kind == "string"):
            raise TypeCheckError("'in' requires a string literal on the left")
        if not isinstance(expr.right, P.ColumnRef):
            raise TypeCheckError("'in' requires a string column on the right")
        right = self.column(expr.right.name)
        if not T.is_string(right.type):
            raise TypeCheckError("'in' requires a string column, %r is %s"
                                 % (expr.right.name, T.type_name(right.type)))
        needle = expr.left.value
        ev = right.evaluate

        def contains(r):
            hay = ev(r)
            return hay is not None and needle in hay
        return Compiled(T.BOOL, contains)

    def call(self, expr):
        name = expr.name
        if name not in _TRANSFORM_ARITY:
            raise DslError("unknown transform %r" % name)
        low, high = _TRANSFORM_ARITY[name]
        if not low <= len(expr.args) <= high:
            raise DslError("%s() takes %s argument(s), got %d"
                           % (name, low if low == high else "%d-%d" % (low, high), len(expr.args)))
        args = [self.compile(a) for a in expr.args]
        first = args[0]
        ev = first.evaluate
        if name == "len":
            if not T.is_string(first.type):
                raise TypeCheckError("len() requires a string, got %s" % T.type_name(first.type))
            return Compiled(T.INT, _null_safe(ev, len))
        if name in ("day", "month", "year"):
            if not T.is_timestamp(first.type):
                raise TypeCheckError("%s() requires a timestamp, got %s"
                                     % (name, T.type_name(first.type)))
            return Compiled(T.INT, _null_safe(ev, lambda v: timestamps.calendar_part(v, name)))
        if not T.is_numeric(first.type):
            raise TypeCheckError("round() requires a number, got %s" % T.type_name(first.type))
        if len(args) == 1:
            return Compiled(T.FLOAT, _null_safe(ev, lambda v: round_half_away(v, 0)))
        if not T.is_int(args[1].type):
            raise TypeCheckError("round() digits must be an integer, got %s"
                                 % T.type_name(args[1].type))
        dev = args[1].evaluate

        def rounding(r):
            v, d = ev(r), dev(r)
            if v is None or d is None:
                return None
            return round_half_away(v, d)
        return Compiled(T.FLOAT, rounding)


def _null_safe(ev, fn):
    def apply(r):
        v = ev(r)
        return None if v is None else fn(v)
    return apply


def _comparison(op, le, re_):
    test = {
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
    }[op]

    def compare(r):
        a, b = le(r), re_(r)
        if a is None or b is None:
            return False
        return test(a, b)
    return compare


def _arithmetic(op, le, re_):
    def compute(r):
        a, b = le(r), re_(r)
        if a is None or b is None:
            return None
        try:
            if op == "+":
                v = a + b
            elif op == "-":
                v = a - b
            elif op == "*":
                v = a * b
            else:
                if b == 0:
                    raise ExecutionError("division by zero")
                v = a / b if op == "/" else a % b
        except OverflowError:
            raise ExecutionError("numeric overflow in '%s'" % op)
        return _finite(v)
    return compute
