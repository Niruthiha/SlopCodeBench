"""Definition records reported by `infer` and `goto`."""
import ast
import inspect
import os
import re
import sys
from dataclasses import asdict, dataclass

from .inference import BuiltinBinding
from .scopes import CLASS, FUNCTION, Binding
from .values import (
    LocalClass,
    LocalFunction,
    LocalInstance,
    LocalModule,
    RuntimeClass,
    RuntimeFunction,
    RuntimeInstance,
    RuntimeModule,
)

_DEFINITION_HEADER = re.compile(r"(?:async\s+)?(?:def|class)\s+")


@dataclass
class Definition:
    name: str
    type: str
    full_name: str
    module_path: str
    line: int
    column: int
    description: str
    docstring: str

    def to_dict(self):
        return asdict(self)

    @property
    def sort_key(self):
        return (self.module_path, self.line, self.column)


def sorted_unique(definitions):
    """Definitions without duplicates, sorted by (module_path, line, column)."""
    seen = set()
    result = []
    for definition in definitions:
        if definition is None:
            continue
        identity = tuple(definition.to_dict().items())
        if identity not in seen:
            seen.add(identity)
            result.append(definition)
    return sorted(result, key=lambda d: d.sort_key)


def normalize(text):
    return re.sub(r"\s+", " ", text).strip()


def char_column(context, line, byte_col):
    """Convert a UTF-8 byte offset on `line` to a character offset."""
    if not 1 <= line <= len(context.lines):
        return byte_col
    encoded = context.lines[line - 1].encode("utf-8")
    return len(encoded[:byte_col].decode("utf-8", errors="ignore"))


def posix_path(path):
    return path.replace(os.sep, "/") if os.sep != "/" else path


def find_word(text, word, start=0):
    """Column of the identifier `word` in `text` at or after `start`, or None."""
    match = re.compile(r"(?<![\w])" + re.escape(word) + r"(?![\w])").search(text, max(start, 0))
    return match.start() if match else None


class DefinitionFactory:
    """Builds Definition records for bindings and inferred values."""

    def __init__(self, inferrer, project_root):
        self.inferrer = inferrer
        self.project_root = os.path.abspath(project_root)

    # -- modules and paths -----------------------------------------------------

    def relative_path(self, path):
        """`path` relative to the project root (absolute outside it), with `/` separators."""
        if not path:
            return ""
        path = os.path.abspath(path)
        try:
            relative = os.path.relpath(path, self.project_root)
        except ValueError:
            return posix_path(path)
        if relative == os.pardir or relative.startswith(os.pardir + os.sep):
            return posix_path(path)
        return posix_path(relative)

    def module_name(self, context):
        """Dotted module name of a parsed file, relative to the project root."""
        if not context.path:
            return context.name
        relative = self.relative_path(context.path)
        if os.path.isabs(relative):
            if context.name and context.name != "__main__":
                return context.name
            relative = os.path.basename(relative)
        stem = os.path.splitext(relative)[0]
        parts = [p for p in stem.split("/") if p]
        if len(parts) > 1 and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    def qualified_name(self, scope):
        """Dotted name of a scope: module, then enclosing classes and functions."""
        parts = []
        for current in scope.chain():
            if current.kind in (CLASS, FUNCTION):
                parts.append(current.node.name)
        parts.append(self.module_name(scope.module))
        return ".".join(reversed(parts))

    # -- source helpers --------------------------------------------------------

    @staticmethod
    def source(context, node):
        text = None
        try:
            text = ast.get_source_segment(context.text, node)
        except Exception:
            text = None
        if not text:
            try:
                text = ast.unparse(node)
            except Exception:
                text = ""
        return normalize(text)

    def parameters(self, context, arguments):
        """The parameter list of a function, formatted like its source."""

        def param(arg, default=None):
            text = arg.arg
            if arg.annotation is not None:
                text += ": " + self.source(context, arg.annotation)
            if default is not None:
                separator = " = " if arg.annotation is not None else "="
                text += separator + self.source(context, default)
            return text

        parts = []
        positional = arguments.posonlyargs + arguments.args
        defaults = [None] * (len(positional) - len(arguments.defaults)) + list(arguments.defaults)
        for index, arg in enumerate(positional):
            parts.append(param(arg, defaults[index]))
            if arguments.posonlyargs and index == len(arguments.posonlyargs) - 1:
                parts.append("/")
        if arguments.vararg is not None:
            parts.append("*" + param(arguments.vararg))
        elif arguments.kwonlyargs:
            parts.append("*")
        for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
            parts.append(param(arg, default))
        if arguments.kwarg is not None:
            parts.append("**" + param(arguments.kwarg))
        return ", ".join(parts)

    # -- bindings ----------------------------------------------------------------

    def from_source(self, source):
        """A Definition for a Binding, BuiltinBinding or Value."""
        if isinstance(source, BuiltinBinding):
            return self.from_value(source.value())
        if isinstance(source, Binding):
            return self.from_binding(source)
        return self.from_value(source)

    def from_binding(self, binding):
        context = binding.scope.module
        line, column = self.binding_position(binding)
        owner = binding.extra.get("owner")
        if owner is not None:
            full_name = f"{self.qualified_name(owner)}.{binding.name}"
        else:
            full_name = f"{self.qualified_name(binding.scope)}.{binding.name}"
        docstring = ""
        if binding.kind in ("def", "class"):
            docstring = ast.get_docstring(binding.node) or ""
        return Definition(
            name=binding.name,
            type=self.binding_type(binding),
            full_name=full_name,
            module_path=self.relative_path(context.path),
            line=line,
            column=column,
            description=self.binding_description(binding),
            docstring=docstring,
        )

    def binding_type(self, binding):
        kind = binding.kind
        if kind == "def":
            return "function"
        if kind == "class":
            return "class"
        if kind == "param":
            return "param"
        if kind == "import":
            return "module"
        if kind == "importfrom":
            values = self.inferrer.binding_values(binding)
            if values and values[0].kind:
                return values[0].kind
            return "module"
        return "statement"

    def binding_description(self, binding):
        context = binding.scope.module
        node = binding.node
        kind = binding.kind
        if kind == "def":
            return f"def {node.name}({self.parameters(context, node.args)})"
        if kind == "class":
            return f"class {node.name}"
        if kind == "param":
            return f"param {binding.name}"
        if kind in ("import", "importfrom"):
            return normalize(ast.unparse(node))
        if kind == "assign":
            if isinstance(node, (ast.Assign, ast.NamedExpr)) or (
                    isinstance(node, ast.AnnAssign) and node.value is not None):
                return self.source(context, node.value)
            return self.source(context, node)
        if kind in ("loop", "comprehension"):
            return f"for {self.source(context, node.target)} in {self.source(context, node.iter)}"
        if kind == "with":
            items = ", ".join(self.source(context, item) for item in node.items)
            return f"with {items}"
        if kind == "except":
            if node.type is None:
                return "except"
            return f"except {self.source(context, node.type)} as {binding.name}"
        if kind == "pattern":
            return f"case {self.source(context, node.pattern)}"
        return self.source(context, node)

    def binding_position(self, binding):
        """(1-based line, 0-based character column) of the bound identifier."""
        context = binding.scope.module
        target = binding.target
        node = binding.node
        lines = context.lines

        def text(line):
            return lines[line - 1] if 1 <= line <= len(lines) else ""

        if isinstance(target, (ast.Name, ast.arg)):
            return target.lineno, char_column(context, target.lineno, target.col_offset)
        if isinstance(target, ast.Attribute):
            end = char_column(context, target.end_lineno, target.end_col_offset)
            return target.end_lineno, end - len(target.attr)
        if isinstance(target, ast.alias):
            start = char_column(context, target.lineno, target.col_offset)
            if target.asname:
                found = find_word(text(target.lineno), target.asname, start + len(target.name))
                if found is not None:
                    return target.lineno, found
            return target.lineno, start
        if binding.kind in ("def", "class"):
            start = char_column(context, node.lineno, node.col_offset)
            match = _DEFINITION_HEADER.match(text(node.lineno), start)
            if match:
                return node.lineno, match.end()
            return node.lineno, start
        if binding.kind == "except":
            for line in range(node.lineno, (node.body[0].lineno if node.body else node.lineno) + 1):
                match = re.search(r"\bas\s+(" + re.escape(binding.name) + r")\b", text(line))
                if match:
                    return line, match.start(1)
        if isinstance(target, ast.pattern):
            for line in range(target.lineno, target.end_lineno + 1):
                start = char_column(context, line, target.col_offset) if line == target.lineno else 0
                found = find_word(text(line), binding.name, start)
                if found is not None:
                    return line, found
        if binding.kind == "importfrom" and isinstance(node, ast.ImportFrom):
            star = text(node.lineno).find("*")
            if star >= 0:
                return node.lineno, star
        found = find_word(text(binding.line), binding.name)
        return binding.line, found if found is not None else 0

    # -- values --------------------------------------------------------------------

    def from_value(self, value):
        if value is None:
            return None
        if isinstance(value, (LocalFunction, LocalClass)):
            return self._local_definition(value)
        if isinstance(value, LocalInstance):
            definition = self._local_definition(value.cls)
            if definition is None:
                return None
            definition.type = "instance"
            definition.description = f"instance of {value.cls.name}"
            return definition
        if isinstance(value, LocalModule):
            context = value.context
            name = self.module_name(context)
            return Definition(
                name=name.split(".")[-1],
                type="module",
                full_name=name,
                module_path=self.relative_path(context.location),
                line=1,
                column=0,
                description=f"module {name.split('.')[-1]}",
                docstring=ast.get_docstring(context.tree) or "",
            )
        if isinstance(value, RuntimeModule):
            return self._runtime_module(value.obj)
        if isinstance(value, RuntimeClass):
            return self._runtime_definition(value.obj, "class")
        if isinstance(value, RuntimeFunction):
            return self._runtime_definition(value.obj, "function")
        if isinstance(value, RuntimeInstance):
            return self._runtime_definition(value.cls, "instance")
        return None

    def _local_definition(self, value):
        node = value.scope.node
        context = value.scope.module
        if isinstance(node, ast.Lambda):
            parameters = self.parameters(context, node.args)
            return Definition(
                name="<lambda>",
                type="function",
                full_name=f"{self.qualified_name(value.scope.parent)}.<lambda>",
                module_path=self.relative_path(context.path),
                line=node.lineno,
                column=char_column(context, node.lineno, node.col_offset),
                description=f"def <lambda>({parameters})",
                docstring="",
            )
        binding = context.binding_of(node)
        if binding is None:
            return None
        return self.from_binding(binding)

    def _runtime_module(self, module):
        name = getattr(module, "__name__", "") or ""
        path = getattr(module, "__file__", None) or ""
        if path.endswith((".pyc", ".pyo")):
            path = path[:-1]
        if path and not path.endswith(".py"):
            path = ""
        return Definition(
            name=name.split(".")[-1],
            type="module",
            full_name=name,
            module_path=self.relative_path(path),
            line=1 if path else 0,
            column=0,
            description=f"module {name.split('.')[-1]}",
            docstring=_docstring(module),
        )

    def _runtime_definition(self, obj, kind):
        name = getattr(obj, "__name__", None) or type(obj).__name__
        qualname = getattr(obj, "__qualname__", None) or name
        module = getattr(obj, "__module__", None)
        if not isinstance(module, str):
            owner = getattr(obj, "__objclass__", None) or getattr(getattr(obj, "__self__", None), "__class__", None)
            module = getattr(owner, "__module__", None) if owner is not None else None
        module = module or "builtins"
        builtin = module == "builtins"
        path, line, column = ("", 0, 0) if builtin else _runtime_location(obj, name)
        if kind == "class":
            description = f"class {name}"
        elif kind == "instance":
            description = f"instance of {name}"
        else:
            description = f"def {name}({_runtime_parameters(obj)})"
        return Definition(
            name=name,
            type=kind,
            full_name=f"{module}.{qualname}",
            module_path=self.relative_path(path),
            line=line,
            column=column,
            description=description,
            docstring="" if builtin else _docstring(obj),
        )


def _docstring(obj):
    try:
        return inspect.getdoc(obj) or ""
    except Exception:
        return ""


def _runtime_parameters(obj):
    try:
        signature = inspect.signature(obj)
    except (TypeError, ValueError):
        return "..."
    text = str(signature.replace(return_annotation=inspect.Signature.empty))
    return text[1:-1]


def _runtime_location(obj, name):
    """(path, line, column) of a runtime class or function's source, if available."""
    path = ""
    module = sys.modules.get(getattr(obj, "__module__", None) or "")
    module_file = getattr(module, "__file__", None) or ""
    if module_file.endswith(".py"):
        path = module_file
    try:
        source_file = inspect.getsourcefile(obj)
        lines, start = inspect.getsourcelines(obj)
    except (TypeError, OSError):
        return path, 0, 0
    if not source_file:
        return path, 0, 0
    for offset, text in enumerate(lines):
        match = re.search(r"(?:def|class)\s+(" + re.escape(name) + r")\b", text)
        if match:
            return source_file, start + offset, match.start(1)
    return source_file, start, 0
