"""User-defined functions.

Secret: how --udf files are loaded and how their functions register (the
@udf decorator, a UDFS table, a register(registry) hook, or plain annotated
functions), signature validation, and how a call converts arguments,
propagates nulls, checks results and wraps failures.

A UDF file is Python.  Any of these registers `score(float, float) -> float`:

    @udf(args=["float", "float"], returns="float")
    def score(a, b): ...

    @udf
    def score(a: float, b: float) -> float: ...

    UDFS = {"score": {"fn": score, "args": ["float", "float"], "returns": "float"}}

    def register(registry):
        registry.register("score", score, args=["float", "float"], returns="float")

Without any explicit registration, every public, fully annotated function
defined in the file is registered.
"""

import hashlib
import inspect
import math
import re
import sys
import types
from collections import OrderedDict
from datetime import datetime, timezone

from . import valuetypes as T
from .dsl_parser import AGGREGATE_FUNCTIONS, is_builtin_function
from .errors import ConfigError, ExecutionError, InputError

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED = ("param", "cast", "true", "false", "in", "as") + AGGREGATE_FUNCTIONS
_TYPE_NAMES = {
    "float": T.FLOAT, "double": T.FLOAT, "int": T.INT, "integer": T.INT,
    "string": T.STRING, "str": T.STRING, "bool": T.BOOL, "boolean": T.BOOL,
    "timestamp": T.TIMESTAMP, "datetime": T.TIMESTAMP, "datetime.datetime": T.TIMESTAMP,
}
_PY_TYPES = {float: T.FLOAT, int: T.INT, str: T.STRING, bool: T.BOOL, datetime: T.TIMESTAMP}
_MARK = "__mtl_udf__"


def udf(*arg_types, name=None, args=None, returns=None):
    """Decorator marking a function as a UDF: @udf, @udf("float", returns="float") or
    @udf(args=[...], returns=...)."""
    if len(arg_types) == 1 and callable(arg_types[0]) and args is None and returns is None:
        fn = arg_types[0]
        setattr(fn, _MARK, (name, None, None))
        return fn
    declared = list(arg_types) if arg_types else args

    def mark(fn):
        setattr(fn, _MARK, (name, declared, returns))
        return fn
    return mark


class Udf:
    """One registered function with its static signature."""

    def __init__(self, name, args, returns, fn, digest):
        self.name = name
        self.args = tuple(args)
        self.returns = returns
        self.fn = fn
        self.hash = digest

    def invoke(self, values):
        """Call the function on argument values; nulls in give null out."""
        if any(v is None for v in values):
            return None
        values = [float(v) if t == T.FLOAT else v for t, v in zip(self.args, values)]
        try:
            result = self.fn(*values)
        except Exception as exc:
            raise ExecutionError("udf %s() failed: %s: %s"
                                 % (self.name, type(exc).__name__, exc))
        return self._result(result)

    def _result(self, value):
        if value is None:
            return None
        expected = self.returns
        if expected == T.FLOAT and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = float(value)
            if not math.isfinite(value):
                raise ExecutionError("udf %s() returned a non-finite value" % self.name)
            return value + 0.0
        if expected == T.INT and isinstance(value, int) and not isinstance(value, bool):
            return value
        if expected == T.STRING and isinstance(value, str):
            return value
        if expected == T.BOOL and isinstance(value, bool):
            return value
        if expected == T.TIMESTAMP and isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        raise ExecutionError("udf %s() returned %s %r, expected %s"
                             % (self.name, type(value).__name__, value, expected))


class Registry:
    """The registered UDFs by name."""

    def __init__(self):
        self._udfs = OrderedDict()
        self._origin = None      # (path, file digest) of the file being loaded

    def register(self, name, fn, args=None, returns=None):
        path, digest = self._origin
        where = "UDF file %r" % path
        if not isinstance(name, str) or not _NAME.match(name):
            raise ConfigError("%s: UDF name %r is not an identifier" % (where, name))
        if is_builtin_function(name) or name in _RESERVED:
            raise ConfigError("%s: UDF %r collides with a built-in name" % (where, name))
        if name in self._udfs:
            if self._udfs[name].fn is fn:
                return fn
            raise ConfigError("%s: UDF %r is registered more than once" % (where, name))
        if not callable(fn):
            raise ConfigError("%s: UDF %r is not callable" % (where, name))
        arg_types, return_type = _signature(fn, args, returns, "%s: UDF %r" % (where, name))
        member = hashlib.sha256(digest.encode("ascii") + b"\0" + name.encode("utf-8"))
        self._udfs[name] = Udf(name, arg_types, return_type, fn, member.hexdigest())
        return fn

    def get(self, name):
        return self._udfs.get(name)

    def arities(self):
        return {name: len(f.args) for name, f in self._udfs.items()}

    def __iter__(self):
        return iter(self._udfs.values())


def load(paths):
    """A Registry with the UDFs of every file in `paths` (in order)."""
    registry = Registry()
    for index, path in enumerate(paths):
        _load_file(registry, index, path)
    return registry


def _load_file(registry, index, path):
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise InputError("cannot read UDF file %r: %s" % (path, exc.strerror or exc))
    registry._origin = (path, hashlib.sha256(data).hexdigest())
    module_name = "mtl_udf_%d" % index
    module = types.ModuleType(module_name)
    module.__file__ = path
    module.udf = udf
    sys.modules[module_name] = module
    try:
        code = compile(data, path, "exec")
        exec(code, module.__dict__)
    except (Exception, SystemExit) as exc:
        raise ConfigError("cannot load UDF file %r: %s: %s" % (path, type(exc).__name__, exc))
    namespace = module.__dict__
    before = len(list(registry))

    for value in list(namespace.values()):
        mark = getattr(value, _MARK, None) if callable(value) else None
        if isinstance(mark, tuple) and len(mark) == 3:
            name, args, returns = mark
            registry.register(name or value.__name__, value, args, returns)
    table = namespace.get("UDFS")
    if table is not None:
        _register_table(registry, table, path)
    hook = namespace.get("register")
    if callable(hook) and getattr(hook, _MARK, None) is None:
        try:
            hook(registry)
        except ConfigError:
            raise
        except Exception as exc:
            raise ConfigError("UDF file %r: register() failed: %s: %s"
                              % (path, type(exc).__name__, exc))
    if len(list(registry)) == before:
        for name, value in list(namespace.items()):
            if (inspect.isfunction(value) and value.__module__ == module_name
                    and not name.startswith("_") and _fully_annotated(value)):
                registry.register(name, value)
    if len(list(registry)) == before:
        raise ConfigError("UDF file %r registers no functions" % path)


def _register_table(registry, table, path):
    if isinstance(table, dict):
        items = list(table.items())
    elif isinstance(table, (list, tuple)):
        items = []
        for entry in table:
            if not isinstance(entry, dict) or "name" not in entry:
                raise ConfigError("UDF file %r: UDFS entries must be mappings with a name"
                                  % path)
            items.append((entry["name"], entry))
    else:
        raise ConfigError("UDF file %r: UDFS must be a mapping or a list" % path)
    for name, spec in items:
        if callable(spec):
            registry.register(name, spec)
        elif isinstance(spec, dict):
            fn = spec.get("fn", spec.get("func", spec.get("function")))
            registry.register(name, fn, spec.get("args"), spec.get("returns"))
        elif isinstance(spec, (list, tuple)) and len(spec) == 3:
            registry.register(name, spec[0], spec[1], spec[2])
        else:
            raise ConfigError("UDF file %r: UDFS entry %r is not a function specification"
                              % (path, name))


def _fully_annotated(fn):
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    return (signature.return_annotation is not inspect.Signature.empty
            and all(p.annotation is not inspect.Parameter.empty
                    for p in signature.parameters.values()))


def _signature(fn, args, returns, where):
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        signature = None
    if args is None:
        if signature is None:
            raise ConfigError("%s: cannot determine argument types; declare args" % where)
        args = []
        for parameter in signature.parameters.values():
            if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
                raise ConfigError("%s: variadic parameters are not supported" % where)
            if parameter.annotation is inspect.Parameter.empty:
                raise ConfigError("%s: parameter %r has no type; annotate it or declare args"
                                  % (where, parameter.name))
            args.append(parameter.annotation)
    if returns is None:
        if signature is None or signature.return_annotation is inspect.Signature.empty:
            raise ConfigError("%s: no return type; annotate it or declare returns" % where)
        returns = signature.return_annotation
    if isinstance(args, (str, type)) or not isinstance(args, (list, tuple)):
        raise ConfigError("%s: args must be a list of type names" % where)
    arg_types = [_type(a, where) for a in args]
    if signature is not None:
        try:
            signature.bind(*arg_types)
        except TypeError:
            raise ConfigError("%s: declares %d argument(s) but the function does not accept "
                              "them" % (where, len(arg_types)))
    return arg_types, _type(returns, where)


def _type(annotation, where):
    if isinstance(annotation, str):
        text = annotation.strip()
        m = re.match(r"^(?:typing\.)?Optional\[(.*)\]$", text)
        if m:
            text = m.group(1).strip()
        found = _TYPE_NAMES.get(text.lower())
    else:
        found = _PY_TYPES.get(annotation)
        if found is None:
            members = [a for a in getattr(annotation, "__args__", ()) or ()
                       if a is not type(None)]
            if len(members) == 1:
                found = _PY_TYPES.get(members[0])
    if found is None:
        raise ConfigError("%s: unsupported type %r (expected float, int, string, bool or "
                          "timestamp)" % (where, annotation))
    return found
