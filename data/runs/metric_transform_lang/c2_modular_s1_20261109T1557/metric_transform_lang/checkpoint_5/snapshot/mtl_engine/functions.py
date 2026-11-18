"""Scalar transform functions: arity, type signatures and implementations."""
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation

from . import dtypes
from .errors import TypeCheckError

# name -> (min_args, max_args)
ARITY = {
    "len": (1, 1),
    "day": (1, 1),
    "month": (1, 1),
    "year": (1, 1),
    "round": (1, 2),
    "starts_with": (2, 2),
    "ends_with": (2, 2),
    "contains": (2, 2),
    "coalesce": (2, 2),
    # Context-dependent: typed by the checker, evaluated by the evaluator.
    "param": (1, 1),
    "lag": (2, 2),
    "lead": (2, 2),
}

STRING_PREDICATES = ("starts_with", "ends_with", "contains")
WINDOW_FUNCTIONS = ("lag", "lead")


def result_type(name, arg_types, line):
    """Validate argument types for a call; return the result type."""
    def fail(expected):
        got = ", ".join(arg_types)
        raise TypeCheckError(f"line {line}: {name}() expects {expected}, got ({got})")

    if name == "len":
        if arg_types[0] != dtypes.STRING:
            fail("a string")
        return dtypes.INT
    if name in ("day", "month", "year"):
        if arg_types[0] != dtypes.TIMESTAMP:
            fail("a timestamp")
        return dtypes.INT
    if name == "round":
        if not dtypes.is_numeric(arg_types[0]):
            fail("a number")
        if len(arg_types) == 2 and arg_types[1] != dtypes.INT:
            fail("an integer number of digits")
        return arg_types[0]
    if name in STRING_PREDICATES:
        if arg_types != [dtypes.STRING, dtypes.STRING]:
            fail("two strings")
        return dtypes.BOOL
    if name == "coalesce":
        a, b = arg_types
        if a == b:
            return a
        if dtypes.is_numeric(a) and dtypes.is_numeric(b):
            return dtypes.FLOAT
        fail("two arguments of the same type")
    raise AssertionError(f"unknown function {name}")


def call(name, args):
    """Invoke a transform; null arguments yield null."""
    if any(a is None for a in args):
        return None
    if name == "len":
        return len(args[0])
    if name == "day":
        return args[0].day
    if name == "month":
        return args[0].month
    if name == "year":
        return args[0].year
    if name == "round":
        digits = args[1] if len(args) > 1 else 0
        return round_half_away(args[0], digits)
    if name == "starts_with":
        return args[0].startswith(args[1])
    if name == "ends_with":
        return args[0].endswith(args[1])
    if name == "contains":
        return args[1] in args[0]
    raise AssertionError(f"unknown function {name}")


_DECIMAL_CTX = Context(prec=1000)


def round_half_away(value, digits):
    """Round to `digits` decimal places, ties away from zero."""
    if isinstance(value, int) and not isinstance(value, bool):
        if digits >= 0:
            return value
        dec = Decimal(value)
    else:
        dec = Decimal(repr(value))
    if digits > 400 or digits < -400:
        return value if digits > 0 else type(value)(0)
    quantum = Decimal(1).scaleb(-digits)
    try:
        rounded = dec.quantize(quantum, rounding=ROUND_HALF_UP, context=_DECIMAL_CTX)
    except InvalidOperation:
        return value
    if isinstance(value, int):
        return int(rounded)
    return float(rounded)
