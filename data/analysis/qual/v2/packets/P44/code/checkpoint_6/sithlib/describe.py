"""Formatting of completion `type` and `description` fields."""
from .namespaces import NamespaceValue, runtime_description
from .values import CLASS, FUNCTION, INSTANCE, MODULE

STATEMENT = "statement"
PARAM = "param"
KEYWORD = "keyword"


def describe_value(name, value):
    """(type, description) for a name bound to an inferred value (or None)."""
    if value is None:
        return STATEMENT, STATEMENT
    if isinstance(value, NamespaceValue):
        return value.kind, runtime_description(value.kind)
    if value.kind == MODULE:
        return MODULE, f"module {name}"
    if value.kind == CLASS:
        return CLASS, f"class {name}"
    if value.kind == FUNCTION:
        return FUNCTION, f"def {name}(...)"
    if value.kind == INSTANCE and value.type_name:
        return INSTANCE, f"instance of {value.type_name}"
    return STATEMENT, STATEMENT


def describe_function(name):
    return FUNCTION, f"def {name}(...)"


def describe_class(name):
    return CLASS, f"class {name}"


def describe_module(name):
    return MODULE, f"module {name}"


def describe_param(name):
    return PARAM, f"param {name}"


def describe_keyword(name):
    return KEYWORD, name
