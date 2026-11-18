"""The `signatures` command: the signature of the call surrounding the cursor."""
import ast
import inspect
import keyword
import os
import re
from dataclasses import asdict, dataclass, field

from . import context as cursor_context
from .definitions import DefinitionFactory
from .inference import Inferrer
from .locate import find_scope
from .modules import ModuleContext, Importer
from .parsing import _starts_statement, parse_tolerant
from .scopes import FUNCTION
from .source import load_document
from .stubs import decorator_names
from .values import (
    LocalClass,
    LocalFunction,
    LocalInstance,
    RuntimeClass,
    RuntimeFunction,
)

POSITIONAL_ONLY = "positional-only"
POSITIONAL = "positional"
VAR_POSITIONAL = "var-positional"
KEYWORD_ONLY = "keyword-only"
VAR_KEYWORD = "var-keyword"

_RUNTIME_KINDS = {
    inspect.Parameter.POSITIONAL_ONLY: POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD: POSITIONAL,
    inspect.Parameter.VAR_POSITIONAL: VAR_POSITIONAL,
    inspect.Parameter.KEYWORD_ONLY: KEYWORD_ONLY,
    inspect.Parameter.VAR_KEYWORD: VAR_KEYWORD,
}
_KEYWORD_ARGUMENT = re.compile(r"\s*([^\W\d]\w*)\s*=(?!=)")


@dataclass
class Param:
    name: str
    kind: str
    text: str


@dataclass
class Signature:
    name: str
    params: list
    index: object
    description: str
    docstring: str
    # Sort key: (module path, line); not part of the output.
    location: tuple = field(default=("", 0), repr=False)

    def to_dict(self):
        result = asdict(self)
        del result["location"]
        return result


@dataclass
class Call:
    """A call whose argument list contains the cursor."""

    callee: str
    position: tuple  # (line, byte column) of the opening parenthesis
    arguments: list  # source text of each argument, the last one up to the cursor


def signatures_at(path, line, col, project=None):
    """Signatures of the call around the cursor at 1-based `line`, 0-based `col` of `path`."""
    document = load_document(path)
    document.check_position(line, col)
    call = find_call(document.text_before(line, col))
    if call is None:
        return []
    try:
        expression = ast.parse(call.callee, mode="eval").body
    except (SyntaxError, ValueError):
        return []
    root = os.path.abspath(project or document.directory)
    importer = Importer(root)
    tree = parse_tolerant(document.text, cursor=(line, col))
    context = ModuleContext(document.path, "__main__", tree, document.text)
    importer.register(context)
    inferrer = Inferrer(importer)
    scope = find_scope(context, line, col, document.lines[line - 1])
    builder = SignatureBuilder(inferrer, DefinitionFactory(inferrer, root))
    signatures = []
    seen = set()
    for value in inferrer.infer_values(expression, scope, pos=call.position):
        for signature, params in builder.signatures(value):
            identity = (signature.location, signature.name, tuple(signature.params))
            if identity in seen:
                continue
            seen.add(identity)
            signature.index = parameter_index(params, call.arguments)
            signatures.append(signature)
    return sorted(signatures, key=lambda s: s.location)


# -- locating the call -----------------------------------------------------------------


def find_call(text):
    """The innermost call whose parentheses enclose the end of `text`, or None."""
    stack = []  # [bracket, offset, top-level comma offsets]
    lines = text.split("\n")
    offset = 0
    quote = None
    for line_text in lines:
        if stack and quote is None and _starts_statement(line_text, _line_at(text, stack[0][1])):
            stack.clear()
        i = 0
        while i < len(line_text):
            char = line_text[i]
            if quote is not None:
                if char == "\\":
                    i += 2
                    continue
                if line_text.startswith(quote, i):
                    i += len(quote)
                    quote = None
                    continue
                i += 1
                continue
            if char == "#":
                break
            if char in "\"'":
                quote = char * 3 if line_text.startswith(char * 3, i) else char
                i += len(quote)
                continue
            if char in "([{":
                stack.append([char, offset + i, []])
            elif char in ")]}":
                if stack and "([{"[")]}".index(char)] == stack[-1][0]:
                    stack.pop()
            elif char == "," and stack:
                stack[-1][2].append(offset + i)
            i += 1
        if quote is not None and len(quote) == 1:
            quote = None  # single-quoted strings end with their line
        offset += len(line_text) + 1
    for bracket, start, commas in reversed(stack):
        if bracket != "(":
            continue
        callee = _callee(text[:start])
        if callee is None:
            continue
        bounds = [start] + commas + [len(text)]
        arguments = [text[bounds[i] + 1:bounds[i + 1]] for i in range(len(bounds) - 1)]
        line = text.count("\n", 0, start) + 1
        line_start = text.rfind("\n", 0, start) + 1
        column = len(text[line_start:start].encode("utf-8"))
        return Call(callee, (line, column), arguments)
    return None


def _line_at(text, offset):
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    return text[start:] if end < 0 else text[start:end]


def _callee(before):
    """The called expression ending at the end of `before`, or None if `(` does not start a call."""
    stripped = before.rstrip(" \t")
    if not stripped:
        return None
    last = stripped[-1]
    if cursor_context.is_identifier_char(last):
        start = len(stripped)
        while start > 0 and cursor_context.is_identifier_char(stripped[start - 1]):
            start -= 1
        word = stripped[start:]
        if word[0].isdigit() or keyword.iskeyword(word):
            return None
        if re.search(r"(?<![\w.])(?:def|class)\s+$", stripped[:start]):
            return None
    elif last not in ")]":
        return None
    receiver = cursor_context.extract_receiver(stripped)
    return receiver or None


# -- parameter index ------------------------------------------------------------------


def _classify(argument):
    text = argument.strip()
    if text.startswith("**"):
        return "unpack-keywords", None
    if text.startswith("*"):
        return "unpack", None
    match = _KEYWORD_ARGUMENT.match(text)
    if match:
        return "keyword", match.group(1)
    return "positional", text


def parameter_index(params, arguments):
    """Index of the parameter the last of `arguments` binds to, following Python's rules."""
    *previous, current = [_classify(a) for a in arguments]
    positional_count = 0
    used = set()
    keywords_seen = False
    unpacked = False
    for kind, name in previous:
        if kind == "positional":
            positional_count += 1
        elif kind == "unpack":
            unpacked = True
        elif kind == "keyword":
            used.add(name)
            keywords_seen = True
        else:
            keywords_seen = True
    positional = [i for i, p in enumerate(params) if p.kind in (POSITIONAL_ONLY, POSITIONAL)]
    var_positional = next((i for i, p in enumerate(params) if p.kind == VAR_POSITIONAL), None)
    var_keyword = next((i for i, p in enumerate(params) if p.kind == VAR_KEYWORD), None)
    kind, name = current

    def keyword_index(match):
        filled = {params[i].name for i in positional[:positional_count]}
        for index, param in enumerate(params):
            if param.kind in (POSITIONAL, KEYWORD_ONLY) and match(param.name) \
                    and param.name not in used and param.name not in filled:
                return index
        return var_keyword

    if kind == "keyword":
        for index, param in enumerate(params):
            if param.name == name and param.kind in (POSITIONAL, KEYWORD_ONLY):
                return index
        return var_keyword
    if kind == "unpack-keywords":
        return var_keyword
    if kind == "unpack":
        if var_positional is not None:
            return var_positional
        return positional[positional_count] if positional_count < len(positional) else None
    if keywords_seen:
        # A positional argument cannot follow keywords: a keyword is being typed.
        if name and not name.isidentifier():
            return None
        return keyword_index(lambda candidate: candidate.startswith(name))
    if unpacked:
        return var_positional
    if positional_count < len(positional):
        return positional[positional_count]
    return var_positional


# -- building signatures -------------------------------------------------------------


class SignatureBuilder:
    def __init__(self, inferrer, factory):
        self.inferrer = inferrer
        self.factory = factory

    def signatures(self, value):
        """[(Signature, [Param])] for calling `value`."""
        members = self.inferrer.members
        if isinstance(value, LocalFunction):
            return self._function(value.scope, skip_first=value.bound is not None)
        if isinstance(value, LocalClass):
            return self._class(value)
        if isinstance(value, LocalInstance):
            method = members.find_method(value.cls, "__call__")
            return self._function(method.scope, skip_first=True) if method else []
        if isinstance(value, (RuntimeFunction, RuntimeClass)):
            return self._runtime(value.obj)
        return []

    def _function(self, scope, skip_first, name=None, docstring=None):
        """Signatures of local function `scope` (one per declaration, e.g. overloads)."""
        results = []
        fallback_doc = ast.get_docstring(scope.node) if scope.kind == FUNCTION else None
        for declaration in self.inferrer.declarations(scope):
            node = declaration.node
            context = declaration.module
            params = self._ast_params(context, node.args)
            if skip_first and "staticmethod" not in decorator_names(node):
                for index, param in enumerate(params):
                    if param.kind in (POSITIONAL_ONLY, POSITIONAL):
                        del params[index]
                        break
            label = name or getattr(node, "name", "<lambda>")
            returns = ""
            if name is None and getattr(node, "returns", None) is not None:
                returns = " -> " + self.factory.source(context, node.returns)
            if docstring is not None:
                doc = docstring
            else:
                doc = (ast.get_docstring(node) if not isinstance(node, ast.Lambda) else None)
                doc = doc or fallback_doc or ""
            results.append((self._signature(label, params, returns, doc, context, node), params))
        return results

    def _class(self, cls):
        inferrer = self.inferrer
        members = inferrer.members
        docstring = ast.get_docstring(cls.node) or ""
        init = members.find_method(cls, "__init__")
        if init is None:
            init = self._stub_init(cls)
        if init is not None:
            doc = docstring or ast.get_docstring(init.node) or ""
            return self._function(init.scope, True, name=cls.name, docstring=doc)
        mro = members.mro(cls)
        context = cls.scope.module
        if any("dataclass" in decorator_names(c.node) for c in mro):
            params = []
            for current in reversed(mro):
                params += self._fields(current)
            return [(self._signature(cls.name, params, "", docstring, context, cls.node), params)]
        for current in mro:
            for base in members.runtime_bases(current):
                if base.obj is not object:
                    found = self._runtime(base.obj, name=cls.name, docstring=docstring,
                                          location=self._location(context, cls.node))
                    if found:
                        return found
        return [(self._signature(cls.name, [], "", docstring, context, cls.node), [])]

    def _stub_init(self, cls):
        """`__init__` declared by the stub of a class in the MRO of `cls` lacking one in source."""
        for current in self.inferrer.members.mro(cls):
            stub = self.inferrer.stubs.stub_scope(current.scope)
            if stub is None:
                continue
            for binding in reversed(stub.bindings.get("__init__", [])):
                if binding.kind == "def":
                    scope = stub.module.scope_of(binding.node)
                    if scope is not None:
                        return LocalFunction(scope)
        return None

    def _fields(self, cls):
        """Parameters generated for the annotated fields of a dataclass."""
        context = cls.scope.module
        params = []
        for node in cls.node.body:
            if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
                continue
            annotation = self.factory.source(context, node.annotation)
            if annotation.startswith(("ClassVar", "typing.ClassVar")):
                continue
            text = f"{node.target.id}: {annotation}"
            if node.value is not None:
                text += "=" + self.factory.source(context, node.value)
            params.append(Param(node.target.id, POSITIONAL, text))
        return params

    def _ast_params(self, context, arguments):
        source = self.factory.source

        def render(arg, default=None):
            text = arg.arg
            if arg.annotation is not None:
                text += ": " + source(context, arg.annotation)
            if default is not None:
                text += "=" + source(context, default)
            return text

        params = []
        positional = arguments.posonlyargs + arguments.args
        defaults = [None] * (len(positional) - len(arguments.defaults)) + list(arguments.defaults)
        for index, arg in enumerate(positional):
            kind = POSITIONAL_ONLY if index < len(arguments.posonlyargs) else POSITIONAL
            params.append(Param(arg.arg, kind, render(arg, defaults[index])))
        if arguments.vararg is not None:
            params.append(Param(arguments.vararg.arg, VAR_POSITIONAL, "*" + render(arguments.vararg)))
        for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
            params.append(Param(arg.arg, KEYWORD_ONLY, render(arg, default)))
        if arguments.kwarg is not None:
            params.append(Param(arguments.kwarg.arg, VAR_KEYWORD, "**" + render(arguments.kwarg)))
        return params

    def _location(self, context, node):
        return (self.factory.relative_path(context.path), getattr(node, "lineno", 0))

    def _signature(self, name, params, returns, docstring, context, node):
        description = f"def {name}({', '.join(p.text for p in params)}){returns}"
        return Signature(name, [p.text for p in params], None, description, docstring,
                         self._location(context, node))

    def _runtime(self, obj, name=None, docstring=None, location=None):
        try:
            signature = inspect.signature(obj)
        except (TypeError, ValueError):
            return []
        params = []
        for parameter in signature.parameters.values():
            text = parameter.name
            if parameter.annotation is not parameter.empty:
                text += ": " + _format_annotation(parameter.annotation)
            if parameter.default is not parameter.empty:
                text += "=" + repr(parameter.default)
            kind = _RUNTIME_KINDS[parameter.kind]
            if kind == VAR_POSITIONAL:
                text = "*" + text
            elif kind == VAR_KEYWORD:
                text = "**" + text
            params.append(Param(parameter.name, kind, text))
        returns = ""
        if name is None and signature.return_annotation is not signature.empty:
            returns = " -> " + _format_annotation(signature.return_annotation)
        label = name or getattr(obj, "__name__", None) or type(obj).__name__
        if docstring is None:
            docstring = _runtime_docstring(obj)
        if location is None:
            location = _runtime_location(self.factory, obj)
        description = f"def {label}({', '.join(p.text for p in params)}){returns}"
        return [(Signature(label, [p.text for p in params], None, description, docstring, location),
                 params)]


def _format_annotation(annotation):
    if isinstance(annotation, str):
        return annotation
    return inspect.formatannotation(annotation)


def _runtime_docstring(obj):
    module = getattr(obj, "__module__", None) or "builtins"
    if module == "builtins":
        return ""
    try:
        return inspect.getdoc(obj) or ""
    except Exception:
        return ""


def _runtime_location(factory, obj):
    definition = factory.from_value(RuntimeClass(obj) if inspect.isclass(obj) else RuntimeFunction(obj))
    if definition is None:
        return ("", 0)
    return (definition.module_path, definition.line)
