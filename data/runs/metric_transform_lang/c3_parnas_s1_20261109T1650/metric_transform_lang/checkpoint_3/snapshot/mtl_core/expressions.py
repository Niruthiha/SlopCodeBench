"""Scalar and boolean expressions.

Secret: the static typing rules applied to expressions and transforms and
how they are evaluated -- null propagation and three-valued logic, half-away-from-zero rounding,
casts, parameter constants, row-relative lag/lead access, and detection of
arithmetic faults (division by zero, non-finite results).
"""

import math
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from . import program as P
from . import timestamps
from . import valuetypes as T
from .errors import DslError, ExecutionError, TypeCheckError

_ORDERING = ("<", "<=", ">", ">=")
_EQUALITY = ("==", "!=")
_ARITHMETIC = ("+", "-", "*", "/", "%")
_TRANSFORM_ARITY = {
    "len": (1, 1), "day": (1, 1), "month": (1, 1), "year": (1, 1), "round": (1, 2),
    "coalesce": (2, None), "lag": (1, 2), "lead": (1, 2),
    "starts_with": (2, 2), "ends_with": (2, 2), "contains": (2, 2),
}
_STRING_TESTS = {
    "starts_with": lambda s, x: s.startswith(x),
    "ends_with": lambda s, x: s.endswith(x),
    "contains": lambda s, x: x in s,
}
_INT_TEXT = re.compile(r"^[+-]?\d+$")
_CASTS = {
    T.INT: (T.INT, T.FLOAT, T.BOOL, T.STRING, T.TIMESTAMP),
    T.FLOAT: (T.INT, T.FLOAT, T.BOOL, T.STRING, T.TIMESTAMP),
    T.STRING: (T.INT, T.FLOAT, T.BOOL, T.STRING, T.TIMESTAMP),
    T.BOOL: (T.INT, T.FLOAT, T.BOOL, T.STRING),
    T.TIMESTAMP: (T.INT, T.FLOAT, T.STRING, T.TIMESTAMP),
}


class Compiled:
    """A type-checked expression: `.type` and `.evaluate(record)`."""

    def __init__(self, value_type, evaluate):
        self.type = value_type
        self.evaluate = evaluate


def compile_expression(expr, schema, params=None, row_relative=False, unknown=None,
                       ts_parser=None):
    """Type-check `expr` against `schema` (has/type_of) and return a Compiled.

    params:       name -> (type, value) of the bound pipeline parameters
    row_relative: whether lag()/lead() may be used; records must then expose
                  `position` and `table` (the ordered list of records)
    unknown:      name -> exception raised for references to unknown columns
    ts_parser:    parser used by cast(<string> as timestamp)
    """
    return _Compiler(schema, params or {}, row_relative, unknown, ts_parser).compile(expr)


def column_references(expr):
    """Names of all columns referenced by `expr`, in first-use order."""
    names = []

    def walk(node):
        if isinstance(node, P.ColumnRef):
            if node.name not in names:
                names.append(node.name)
        elif isinstance(node, P.Unary):
            walk(node.operand)
        elif isinstance(node, P.Binary):
            walk(node.left)
            walk(node.right)
        elif isinstance(node, P.Call):
            for arg in node.args:
                walk(arg)
        elif isinstance(node, P.Cast):
            walk(node.operand)
    walk(expr)
    return names


def uses_row_relative(expr):
    """True if `expr` calls lag() or lead()."""
    if isinstance(expr, P.Call):
        return expr.name in ("lag", "lead") or any(uses_row_relative(a) for a in expr.args)
    if isinstance(expr, P.Unary):
        return uses_row_relative(expr.operand)
    if isinstance(expr, P.Binary):
        return uses_row_relative(expr.left) or uses_row_relative(expr.right)
    if isinstance(expr, P.Cast):
        return uses_row_relative(expr.operand)
    return False


def is_assignable(declared, actual):
    """Whether a value of type `actual` may be stored as `declared` (int widens to float)."""
    return declared == actual or (declared == T.FLOAT and actual == T.INT)


def coerce(declared, compiled):
    """Evaluator storing compiled's value as `declared` (see is_assignable)."""
    ev = compiled.evaluate
    if declared == T.FLOAT and compiled.type == T.INT:
        return _null_safe(ev, float)
    return ev


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
    def __init__(self, schema, params, row_relative, unknown, ts_parser):
        self.schema = schema
        self.params = params
        self.row_relative = row_relative
        self.unknown = unknown or (lambda name: TypeCheckError("unknown column %r" % name))
        self.ts_parser = ts_parser

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
        if isinstance(expr, P.Param):
            return self.param(expr.name)
        if isinstance(expr, P.Cast):
            return self.cast(expr)
        raise DslError("unsupported expression")

    def literal(self, expr):
        value_type = {"int": T.INT, "float": T.FLOAT, "string": T.STRING, "bool": T.BOOL}[expr.kind]
        value = expr.value
        if isinstance(value, float):
            _finite(value)
        return Compiled(value_type, lambda record: value)

    def column(self, name):
        if not self.schema.has(name):
            raise self.unknown(name)
        return Compiled(self.schema.type_of(name), lambda record: record.get(name))

    def param(self, name):
        if name not in self.params:
            raise DslError("unknown parameter %r" % name)
        value_type, value = self.params[name]
        return Compiled(value_type, lambda record: value)

    def cast(self, expr):
        inner = self.compile(expr.operand)
        source, target = inner.type, expr.type
        if target not in _CASTS.get(source, ()):
            raise TypeCheckError("cannot cast %s to %s" % (T.type_name(source), T.type_name(target)))
        convert = _caster(source, target, self.ts_parser)
        return Compiled(target, _null_safe(inner.evaluate, convert))

    def unary(self, expr):
        inner = self.compile(expr.operand)
        ev = inner.evaluate
        if expr.op == "!":
            if not T.is_bool(inner.type):
                raise TypeCheckError("'!' requires a boolean operand, got %s" % T.type_name(inner.type))
            return Compiled(T.BOOL, _null_safe(ev, lambda v: not v))
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
            return Compiled(T.BOOL, _kleene_and(le, re_) if op == "&" else _kleene_or(le, re_))
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
        if isinstance(expr.left, P.Param):
            needle_c = self.param(expr.left.name)
            if not T.is_string(needle_c.type):
                raise TypeCheckError("'in' requires a string on the left, got %s"
                                     % T.type_name(needle_c.type))
            expr = expr._replace(left=P.Literal("string", needle_c.evaluate(None)))
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
            return None if hay is None else needle in hay
        return Compiled(T.BOOL, contains)

    def call(self, expr):
        name = expr.name
        if name not in _TRANSFORM_ARITY:
            raise DslError("unknown transform %r" % name)
        low, high = _TRANSFORM_ARITY[name]
        if len(expr.args) < low or (high is not None and len(expr.args) > high):
            raise DslError("wrong number of arguments to %s(): %d" % (name, len(expr.args)))
        if name in ("lag", "lead"):
            return self.shifted(expr)
        args = [self.compile(a) for a in expr.args]
        if name == "coalesce":
            return self.coalesce(args)
        if name in _STRING_TESTS:
            return self.string_test(name, args)
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

    def coalesce(self, args):
        types = [a.type for a in args]
        if all(t == types[0] for t in types):
            result_type = types[0]
        elif all(T.is_numeric(t) for t in types):
            result_type = T.FLOAT
        else:
            raise TypeCheckError("coalesce() arguments must share a type, got %s"
                                 % ", ".join(T.type_name(t) for t in types))
        evs = [coerce(result_type, a) for a in args]

        def first_present(r):
            for ev in evs:
                v = ev(r)
                if v is not None and not (isinstance(v, float) and not math.isfinite(v)):
                    return v
            return None
        return Compiled(result_type, first_present)

    def string_test(self, name, args):
        if not all(T.is_string(a.type) for a in args):
            raise TypeCheckError("%s() requires string arguments, got %s"
                                 % (name, ", ".join(T.type_name(a.type) for a in args)))
        test = _STRING_TESTS[name]
        hay, needle = args[0].evaluate, args[1].evaluate

        def check(r):
            h, n = hay(r), needle(r)
            if h is None or n is None:
                return None
            return test(h, n)
        return Compiled(T.BOOL, check)

    def shifted(self, expr):
        name = expr.name
        if not self.row_relative:
            raise DslError("%s() is only allowed in @stage(post_agg) calcs" % name)
        inner = self.compile(expr.args[0])
        k = self.offset(name, expr.args[1]) if len(expr.args) > 1 else 1
        step = -k if name == "lag" else k
        ev = inner.evaluate

        def neighbour(r):
            j = r.position + step
            if j < 0 or j >= len(r.table):
                return None
            return ev(r.table[j])
        return Compiled(inner.type, neighbour)

    def offset(self, name, arg):
        if isinstance(arg, P.Literal):
            if arg.kind != "int":
                raise TypeCheckError("%s() offset must be an int, got %s" % (name, arg.kind))
            if arg.value <= 0:
                raise DslError("%s() offset must be a positive integer" % name)
            return arg.value
        if isinstance(arg, P.Param):
            compiled = self.param(arg.name)
            if not T.is_int(compiled.type):
                raise TypeCheckError("%s() offset parameter %r must be an int, got %s"
                                     % (name, arg.name, T.type_name(compiled.type)))
            k = compiled.evaluate(None)
            if k <= 0:
                raise ExecutionError("%s() offset must be positive, parameter %r is %d"
                                     % (name, arg.name, k))
            return k
        raise DslError("%s() offset must be a positive integer literal or an int param()" % name)


def _caster(source, target, ts_parser):
    if source == target:
        return lambda v: v
    if target == T.STRING:
        if source == T.BOOL:
            return lambda v: "true" if v else "false"
        if source == T.TIMESTAMP:
            return timestamps.format_utc
        if source == T.FLOAT:
            return lambda v: repr(v + 0.0)
        return str
    if source == T.STRING:
        return _string_parser(target, ts_parser)
    if source == T.TIMESTAMP:
        micros = timestamps.to_epoch_micros
        if target == T.INT:
            return lambda v: micros(v) // 1000000
        return lambda v: micros(v) / 1000000.0
    if target == T.TIMESTAMP:
        return lambda v: timestamps.from_epoch_micros(int(round(v * 1000000)))
    if target == T.BOOL:
        return lambda v: v != 0
    if target == T.INT:
        return lambda v: int(v)
    return lambda v: _finite(float(v))


def _string_parser(target, ts_parser):
    def parse(text):
        stripped = text.strip()
        if stripped == "":
            return None
        try:
            if target == T.INT:
                if _INT_TEXT.match(stripped):
                    return int(stripped)
                return int(_finite_text(stripped))
            if target == T.FLOAT:
                return _finite_text(stripped)
            if target == T.BOOL:
                lowered = stripped.lower()
                if lowered in ("true", "false"):
                    return lowered == "true"
                raise ValueError(text)
            if ts_parser is not None:
                return ts_parser.parse(stripped)
            return timestamps.TimestampParser().parse(stripped)
        except (ValueError, OverflowError):
            raise ExecutionError("cannot cast %r to %s" % (text, T.type_name(target)))
    return parse


def _finite_text(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(text)
    return value


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
            return None
        return test(a, b)
    return compare


def _kleene_and(le, re_):
    def conjunction(r):
        a = le(r)
        if a is False:
            return False
        b = re_(r)
        if b is False:
            return False
        return None if a is None or b is None else True
    return conjunction


def _kleene_or(le, re_):
    def disjunction(r):
        a = le(r)
        if a is True:
            return True
        b = re_(r)
        if b is True:
            return True
        return None if a is None or b is None else False
    return disjunction


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
