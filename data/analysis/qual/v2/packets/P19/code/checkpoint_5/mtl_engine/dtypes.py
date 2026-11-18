"""Value types of the MTL type system."""
import re

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


_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_BOOLS = {"true": True, "false": False}


def looks_like(text, t):
    """Whether stripped text is a valid literal of int, float or bool type."""
    if t == INT:
        return bool(_INT_RE.match(text))
    if t == FLOAT:
        return bool(_FLOAT_RE.match(text))
    if t == BOOL:
        return text.lower() in _BOOLS
    raise AssertionError(f"no text form check for {t}")


def parse_text(text, t):
    """Parse stripped text as an int, float or bool; raise ValueError when invalid."""
    if not looks_like(text, t):
        raise ValueError(f"not a valid {t}")
    if t == INT:
        return int(text)
    if t == FLOAT:
        value = float(text)
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("not a finite number")
        return value
    return _BOOLS[text.lower()]
