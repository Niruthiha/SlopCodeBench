"""User-defined scalar functions loaded from Python files given with --udf.

A UDF file declares its functions in one of three ways (checked in this order):

* a `register(registry)` function calling `registry.register(name, func, args, returns)`
  (or `registry(name, args=..., returns=...)` as a decorator factory);
* a `UDFS` dict mapping name -> {"func": callable, "args": [types], "returns": type}
  (a bare callable value is typed from its annotations);
* public module-level functions whose parameters and return are annotated.

Types are DSL type names (int, float, string, bool, timestamp) or the Python types
int, float, str, bool and datetime.
"""
import hashlib
import importlib.util
import inspect
import keyword
import math
import re
import sys
from datetime import datetime, timezone

from . import dtypes
from .errors import ConfigError, IOFailure, RuntimeFailure

# name -> Udf, filled by load() before the DSL is parsed.
REGISTRY = {}

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
_TYPE_ALIASES = {
    "int": dtypes.INT, "integer": dtypes.INT, "long": dtypes.INT,
    "float": dtypes.FLOAT, "double": dtypes.FLOAT, "number": dtypes.FLOAT,
    "string": dtypes.STRING, "str": dtypes.STRING, "text": dtypes.STRING,
    "bool": dtypes.BOOL, "boolean": dtypes.BOOL,
    "timestamp": dtypes.TIMESTAMP, "datetime": dtypes.TIMESTAMP,
}
_PY_TYPES = {int: dtypes.INT, float: dtypes.FLOAT, str: dtypes.STRING, bool: dtypes.BOOL,
             datetime: dtypes.TIMESTAMP}
# Names a UDF may not take: built-in functions, aggregates and keywords of the DSL.
_RESERVED = {"len", "day", "month", "year", "round", "starts_with", "ends_with", "contains",
             "coalesce", "param", "lag", "lead", "cast", "average", "median", "sum", "count",
             "std", "var", "min", "max", "true", "false", "in", "filter", "apply", "group_by",
             "window", "aggregate", "calc", "schema", "pipeline", "params", "sources", "with",
             "join", "mtl_version"}


class Udf:
    def __init__(self, name, func, args, returns, digest):
        self.name = name
        self.func = func
        self.args = args
        self.returns = returns
        self.hash = digest

    def to_json(self):
        return {"name": self.name, "args": list(self.args), "returns": self.returns,
                "hash": self.hash}


class _Registry:
    """Handed to a UDF file's register() function."""

    def __init__(self, path, digest):
        self.path = path
        self.digest = digest
        self.found = []

    def register(self, name, func=None, args=None, returns=None):
        if func is None:
            def decorator(fn):
                self.register(name, fn, args, returns)
                return fn
            return decorator
        self.found.append(_make(name, func, args, returns, self.path, self.digest))
        return func

    __call__ = register


def load(paths):
    """Load every UDF file, replacing the registry contents."""
    REGISTRY.clear()
    for idx, path in enumerate(paths):
        for udf in _load_file(path, idx):
            if udf.name in REGISTRY:
                raise ConfigError(f"UDF '{udf.name}' is registered more than once")
            REGISTRY[udf.name] = udf


def metadata():
    """Registered UDFs, sorted by name then signature."""
    return [u.to_json() for u in sorted(REGISTRY.values(),
                                        key=lambda u: (u.name, list(u.args), u.returns))]


def _load_file(path, idx):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise IOFailure(f"cannot read UDF file '{path}': {exc}") from exc
    digest = hashlib.sha256(data).hexdigest()
    module_name = f"_mtl_udf_{idx}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ConfigError(f"UDF file '{path}' is not a Python module")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except ConfigError:
        raise
    except BaseException as exc:  # arbitrary user code: any failure is a registration error
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise ConfigError(f"cannot load UDF file '{path}': {type(exc).__name__}: {exc}") from exc

    register = getattr(module, "register", None)
    if callable(register):
        registry = _Registry(path, digest)
        try:
            register(registry)
        except ConfigError:
            raise
        except Exception as exc:
            raise ConfigError(f"UDF registration in '{path}' failed: {exc}") from exc
        found = registry.found
    elif isinstance(getattr(module, "UDFS", None), dict):
        found = []
        for name, spec in module.UDFS.items():
            if callable(spec):
                found.append(_make(name, spec, None, None, path, digest))
            elif isinstance(spec, dict):
                func = spec.get("func", spec.get("fn", spec.get("function")))
                args = spec.get("args", spec.get("arg_types", spec.get("params")))
                returns = spec.get("returns", spec.get("return_type", spec.get("return")))
                found.append(_make(name, func, args, returns, path, digest))
            else:
                raise ConfigError(f"UDF '{name}' in '{path}' must be a function or a mapping")
    else:
        found = [_make(name, obj, None, None, path, digest)
                 for name, obj in vars(module).items()
                 if inspect.isfunction(obj) and obj.__module__ == module_name
                 and not name.startswith("_")]
    if not found:
        raise ConfigError(f"UDF file '{path}' does not register any function")
    return found


def _make(name, func, args, returns, path, digest):
    if not isinstance(name, str) or not _NAME_RE.match(name) or keyword.iskeyword(name):
        raise ConfigError(f"invalid UDF name {name!r} in '{path}'")
    if name in _RESERVED:
        raise ConfigError(f"UDF '{name}' in '{path}' clashes with a built-in name")
    if not callable(func):
        raise ConfigError(f"UDF '{name}' in '{path}' is not callable")
    if args is None or returns is None:
        try:
            sig = inspect.signature(func)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"UDF '{name}' in '{path}' has no inspectable signature") from exc
        if args is None:
            args = []
            for param in sig.parameters.values():
                if param.kind not in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD):
                    raise ConfigError(f"UDF '{name}' in '{path}' must take positional "
                                      "parameters only")
                if param.annotation is inspect.Parameter.empty:
                    raise ConfigError(f"UDF '{name}' in '{path}': parameter '{param.name}' "
                                      "needs a type annotation")
                args.append(param.annotation)
        if returns is None:
            if sig.return_annotation is inspect.Signature.empty:
                raise ConfigError(f"UDF '{name}' in '{path}' needs a return type annotation")
            returns = sig.return_annotation
    if isinstance(args, (str, type)) or not isinstance(args, (list, tuple)):
        raise ConfigError(f"UDF '{name}' in '{path}': 'args' must be a list of types")
    arg_types = [_dsl_type(a, name, path) for a in args]
    return Udf(name, func, arg_types, _dsl_type(returns, name, path), digest)


def _dsl_type(value, name, path):
    if isinstance(value, type) and value in _PY_TYPES:
        return _PY_TYPES[value]
    if isinstance(value, str) and value.strip().lower() in _TYPE_ALIASES:
        return _TYPE_ALIASES[value.strip().lower()]
    raise ConfigError(f"UDF '{name}' in '{path}' uses unsupported type {value!r}")


# --------------------------------------------------------------------------- typing / calls


def result_type(udf, arg_types, line):
    from .errors import TypeCheckError

    for idx, (want, got) in enumerate(zip(udf.args, arg_types), start=1):
        if not (want == got or (want == dtypes.FLOAT and got == dtypes.INT)):
            raise TypeCheckError(f"line {line}: argument {idx} of {udf.name}() must be {want}, "
                                 f"got {got}")
    return udf.returns


def call(udf, args, line):
    """Invoke a UDF; null arguments yield null. A result of the wrong type is a TypeError
    (rejected as TYPE_ERROR), any exception a runtime error."""
    if any(a is None for a in args):
        return None
    args = [float(a) if t == dtypes.FLOAT and isinstance(a, int) else a
            for a, t in zip(args, udf.args)]
    try:
        result = udf.func(*args)
    except Exception as exc:
        raise RuntimeFailure(f"line {line}: UDF {udf.name}() failed: "
                             f"{type(exc).__name__}: {exc}") from exc
    if result is None:
        return None
    want = udf.returns
    if want == dtypes.FLOAT and isinstance(result, int) and not isinstance(result, bool):
        result = float(result)
    if want == dtypes.TIMESTAMP and isinstance(result, datetime):
        result = (result.replace(tzinfo=timezone.utc) if result.tzinfo is None
                  else result.astimezone(timezone.utc))
    if not _conforms(result, want):
        raise TypeError(f"UDF {udf.name}() returned {type(result).__name__}, expected {want}")
    if want == dtypes.FLOAT and not math.isfinite(result):
        raise RuntimeFailure(f"line {line}: UDF {udf.name}() returned a non-finite number")
    return result


def _conforms(value, t):
    if t == dtypes.BOOL:
        return isinstance(value, bool)
    if t == dtypes.INT:
        return isinstance(value, int) and not isinstance(value, bool)
    if t == dtypes.FLOAT:
        return isinstance(value, float)
    if t == dtypes.STRING:
        return isinstance(value, str)
    return isinstance(value, datetime) and value.tzinfo is not None
