"""Call signatures (``signatures``).

Secret: how the callable whose argument list holds the cursor is turned into
signatures (functions and bound methods, classes through their initializer
or dataclass fields, callable instances, overloads and stub declarations,
runtime callables), how parameters and signatures are rendered, and how the
arguments typed so far are bound to parameters to find the active one.
"""

import ast
import inspect
import re

from . import cursor, navigation
from .inference import (Project, RuntimeValue, StaticClass, StaticFunction, StaticInstance,
                        CLASS, FUNCTION)
from .source import SourceFile

POSITIONAL_ONLY = "positional_only"
POSITIONAL_OR_KEYWORD = "positional_or_keyword"
VAR_POSITIONAL = "var_positional"
KEYWORD_ONLY = "keyword_only"
VAR_KEYWORD = "var_keyword"

_RUNTIME_KINDS = {
    inspect.Parameter.POSITIONAL_ONLY: POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD: POSITIONAL_OR_KEYWORD,
    inspect.Parameter.VAR_POSITIONAL: VAR_POSITIONAL,
    inspect.Parameter.KEYWORD_ONLY: KEYWORD_ONLY,
    inspect.Parameter.VAR_KEYWORD: VAR_KEYWORD,
}


class Parameter:
    def __init__(self, name, kind, text):
        self.name = name
        self.kind = kind
        self.text = text


class Signature:
    def __init__(self, name, params, returns, docstring, module_path, line):
        self.name = name
        self.params = params
        self.returns = returns  # rendered return annotation, or None
        self.docstring = docstring or ""
        self.module_path = module_path
        self.line = line

    def description(self):
        parts = []
        star_seen = False
        previous = None
        for param in self.params:
            if previous == POSITIONAL_ONLY and param.kind != POSITIONAL_ONLY:
                parts.append("/")
            if param.kind == VAR_POSITIONAL:
                star_seen = True
            elif param.kind == KEYWORD_ONLY and not star_seen:
                parts.append("*")
                star_seen = True
            parts.append(param.text)
            previous = param.kind
        if previous == POSITIONAL_ONLY:
            parts.append("/")
        text = "def %s(%s)" % (self.name, ", ".join(parts))
        return text + " -> " + self.returns if self.returns else text

    def active_index(self, arguments):
        """Index of the parameter bound to the last of ``arguments`` (see cursor), or None."""
        params = self.params
        star = _first(params, VAR_POSITIONAL)
        double_star = _first(params, VAR_KEYWORD)
        shape, keyword = arguments[-1]
        if shape == cursor.KEYWORD:
            for index, param in enumerate(params):
                if param.name == keyword and param.kind in (POSITIONAL_OR_KEYWORD, KEYWORD_ONLY):
                    return index
            return double_star
        if shape == cursor.DOUBLE_STAR:
            return double_star
        if shape == cursor.STAR:
            return star
        before = arguments[:-1]
        if any(s in (cursor.KEYWORD, cursor.DOUBLE_STAR) for s, _ in before):
            return None
        position = sum(1 for s, _ in before if s == cursor.POSITIONAL)
        positional = [i for i, p in enumerate(params)
                      if p.kind in (POSITIONAL_ONLY, POSITIONAL_OR_KEYWORD)]
        if position < len(positional):
            return positional[position]
        return star


def _first(params, kind):
    for index, param in enumerate(params):
        if param.kind == kind:
            return index
    return None


def signatures(path, line, col, root=None):
    """Signatures (as dicts) of the call whose argument list holds the cursor."""
    source = SourceFile(path)
    source.check_position(line, col)
    context = cursor.call_context(source.text_before(line, col))
    if context is None:
        return []
    project = Project(source.path, source.text(), root)
    text = source.lines()[line - 1]
    indent = len(text) - len(text.lstrip()) if text[:col].strip() else col
    builder = _Builder(project)
    found = []
    for value in project.location(line, col, indent).evaluate(context.callee):
        found.extend(builder.signatures(value))
    unique = {}
    for signature in found:
        key = (signature.module_path, signature.line, signature.name, signature.description())
        unique.setdefault(key, signature)
    ordered = sorted(unique.values(), key=lambda s: (s.module_path, s.line))
    return [{"name": s.name, "params": [p.text for p in s.params],
             "index": s.active_index(context.arguments), "description": s.description(),
             "docstring": s.docstring} for s in ordered]


class _Builder:
    def __init__(self, project):
        self._describer = navigation.describer(project)

    def signatures(self, value):
        if isinstance(value, StaticFunction):
            return self._function(value, value.scope.name, skip_first=value.bound is not None)
        if isinstance(value, StaticClass):
            return self._class(value)
        if isinstance(value, StaticInstance):
            result = []
            for method in value.attribute("__call__"):
                if isinstance(method, StaticFunction):
                    result.extend(self._function(method, method.scope.name,
                                                 skip_first=method.bound is not None))
            return result
        if isinstance(value, RuntimeValue) and value.kind in (FUNCTION, CLASS):
            found = _runtime(value.obj)
            return [found] if found is not None else []
        return []

    def _function(self, function, name, skip_first, docstring=None, returns=True):
        own_doc = _docstring(function.scope.node)
        result = []
        for analysis, scope in function.declarations():
            params = _parameters(analysis.tree, scope.node, skip_first)
            annotation = scope.node.returns if returns else None
            doc = docstring if docstring is not None else (own_doc or _docstring(scope.node))
            line, _ = analysis.tree.definition_position(scope.node)
            result.append(Signature(name, params,
                                    _source(analysis.tree, annotation) if annotation else None,
                                    doc, self._describer.relative(analysis.path), line))
        return result

    def _class(self, cls):
        name = cls.name
        doc = _docstring(cls.scope.node)
        if not doc:
            stub_scope = cls.stub_scope()
            doc = _docstring(stub_scope.node) if stub_scope is not None else ""
        result = []
        for init in cls.attribute("__init__"):
            if isinstance(init, StaticFunction):
                result.extend(self._function(init, name, skip_first=True, docstring=doc,
                                             returns=False))
        if result:
            return result
        tree = cls.scope.tree
        line, _ = tree.definition_position(cls.scope.node)
        params = _dataclass_fields(cls) if _is_dataclass(cls.scope.node) else []
        return [Signature(name, params, None, doc, self._describer.relative(tree.path), line)]


def _parameters(tree, node, skip_first):
    args = node.args
    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    params = []
    for index, (arg, default) in enumerate(zip(positional, defaults)):
        kind = POSITIONAL_ONLY if index < len(args.posonlyargs) else POSITIONAL_OR_KEYWORD
        params.append(_parameter(tree, arg.arg, kind, arg.annotation, default))
    if skip_first and params:
        params.pop(0)
    if args.vararg:
        params.append(_parameter(tree, args.vararg.arg, VAR_POSITIONAL,
                                 args.vararg.annotation, None, "*"))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        params.append(_parameter(tree, arg.arg, KEYWORD_ONLY, arg.annotation, default))
    if args.kwarg:
        params.append(_parameter(tree, args.kwarg.arg, VAR_KEYWORD,
                                 args.kwarg.annotation, None, "**"))
    return params


def _parameter(tree, name, kind, annotation, default, stars=""):
    text = stars + name
    if annotation is not None:
        text += ": " + _source(tree, annotation)
    if default is not None:
        text += "=" + _source(tree, default)
    return Parameter(name, kind, text)


def _source(tree, node):
    """``node`` as written in the source (whitespace collapsed)."""
    segment = tree.segment(node)
    if segment is None:
        try:
            segment = ast.unparse(node)
        except Exception:  # odd trees
            segment = ""
    return re.sub(r"\s+", " ", segment).strip()


def _docstring(node):
    try:
        return ast.get_docstring(node, clean=True) or ""
    except (TypeError, AttributeError):
        return ""


def _is_dataclass(node):
    for decorator in getattr(node, "decorator_list", []):
        if isinstance(decorator, ast.Call):
            decorator = decorator.func
        name = decorator.attr if isinstance(decorator, ast.Attribute) else \
            getattr(decorator, "id", None)
        if name == "dataclass":
            return True
    return False


def _dataclass_fields(cls):
    """Initializer parameters of a dataclass: annotated class attributes, bases first."""
    fields = {}
    for base in reversed(cls.mro()):
        node = base.scope.node
        if not _is_dataclass(node):
            continue
        for statement in node.body:
            if not isinstance(statement, ast.AnnAssign) \
                    or not isinstance(statement.target, ast.Name):
                continue
            annotation = _source(base.scope.tree, statement.annotation)
            if annotation.split("[")[0].split(".")[-1] in ("ClassVar", "KW_ONLY"):
                continue
            name = statement.target.id
            fields.pop(name, None)
            fields[name] = _parameter(base.scope.tree, name, POSITIONAL_OR_KEYWORD,
                                      statement.annotation, statement.value)
    return list(fields.values())


def _runtime(obj):
    try:
        signature = inspect.signature(obj)
    except (TypeError, ValueError):
        return None
    params = []
    for param in signature.parameters.values():
        kind = _RUNTIME_KINDS[param.kind]
        stars = {VAR_POSITIONAL: "*", VAR_KEYWORD: "**"}.get(kind, "")
        text = stars + param.name
        if param.annotation is not inspect.Parameter.empty:
            text += ": " + inspect.formatannotation(param.annotation)
        if param.default is not inspect.Parameter.empty:
            text += "=" + repr(param.default)
        params.append(Parameter(param.name, kind, text))
    returns = None
    if signature.return_annotation is not inspect.Signature.empty:
        returns = inspect.formatannotation(signature.return_annotation)
    name = getattr(obj, "__name__", None) or type(obj).__name__
    try:
        doc = inspect.getdoc(obj) or ""
    except Exception:  # odd objects
        doc = ""
    return Signature(name, params, returns, doc, "", 0)
