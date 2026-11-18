"""Value types of the MTL type system."""

INT = "int"
FLOAT = "float"
STRING = "string"
BOOL = "bool"
TIMESTAMP = "timestamp"

NUMERIC = frozenset({INT, FLOAT})


def is_numeric(t):
    return t in NUMERIC


def numeric_result(*types):
    """Result type of an int/float operation (int only if all operands are int)."""
    return INT if all(t == INT for t in types) else FLOAT


def comparable(a, b, op):
    """Whether values of types a and b may be compared with operator op."""
    if is_numeric(a) and is_numeric(b):
        return True
    if a != b:
        return False
    if a in (STRING, TIMESTAMP):
        return True
    if a == BOOL:
        return op in ("==", "!=")
    return False
