"""Value types of the language.

Secret: the type lattice and its compatibility rules (int<->float widening,
which kinds may be compared or ordered, what counts as numeric).
"""

INT = "int"
FLOAT = "float"
STRING = "string"
TIMESTAMP = "timestamp"
BOOL = "bool"

_NUMERIC = (INT, FLOAT)


def is_numeric(t):
    return t in _NUMERIC


def is_string(t):
    return t == STRING


def is_timestamp(t):
    return t == TIMESTAMP


def is_bool(t):
    return t == BOOL


def is_int(t):
    return t == INT


def _kind(t):
    return "number" if t in _NUMERIC else t


def can_compare(a, b):
    """True if values of types a and b may be tested for (in)equality."""
    return _kind(a) == _kind(b)


def can_order(a, b):
    """True if values of types a and b may be ordered with < <= > >=."""
    return can_compare(a, b) and _kind(a) in ("number", STRING, TIMESTAMP)


def widen(a, b):
    """Result type of an arithmetic operation on two numeric types."""
    return INT if a == INT and b == INT else FLOAT


def type_name(t):
    return t
