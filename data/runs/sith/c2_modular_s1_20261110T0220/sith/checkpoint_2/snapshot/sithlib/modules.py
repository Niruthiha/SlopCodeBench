"""Module contexts and import resolution (local files first, then installed)."""
import contextlib
import importlib
import io
import os
import warnings

from .parsing import parse_tolerant
from .scopes import ScopeBuilder
from .source import read_text
from .errors import SithError
from .values import LocalModule, RuntimeModule


class ModuleContext:
    """A parsed Python module together with its scope tree."""

    def __init__(self, path, name, tree, text=""):
        self.path = os.path.abspath(path) if path else None
        self.directory = os.path.dirname(self.path) if self.path else os.getcwd()
        self.name = name
        self.tree = tree
        self.text = text
        self.lines = text.split("\n")
        builder = ScopeBuilder(self)
        self.root = builder.build(tree)
        self.scope_by_node = builder.scope_by_node
        self.binding_by_target = builder.binding_by_target

    @property
    def is_package(self):
        return bool(self.path) and os.path.basename(self.path) == "__init__.py"

    def scope_of(self, node):
        return self.scope_by_node.get(id(node))

    def binding_of(self, node):
        """The binding created for a name node (or def/class/except node), if any."""
        return self.binding_by_target.get(id(node))


class Importer:
    """Resolves module names to values, preferring files in the project directory."""

    def __init__(self, project_dir, *extra_dirs):
        self.project_dir = project_dir
        self.search_dirs = [project_dir] + [d for d in extra_dirs if d and d != project_dir]
        self._contexts = {}
        self._runtime = {}

    def register(self, context):
        if context.path:
            self._contexts[context.path] = context

    def context_for_file(self, path, name):
        path = os.path.abspath(path)
        if path not in self._contexts:
            try:
                text = read_text(path)
            except SithError:
                return None
            self._contexts[path] = ModuleContext(path, name, parse_tolerant(text), text)
        return self._contexts[path]

    def import_absolute(self, dotted):
        """Resolve `import dotted` to a module value, or None."""
        if not dotted:
            return None
        path = None
        for directory in self.search_dirs:
            path = self._find_local(directory, dotted.split("."))
            if path:
                break
        if path:
            context = self.context_for_file(path, dotted)
            return LocalModule(context) if context else None
        return self._import_runtime(dotted)

    def import_relative(self, context, dotted, level):
        """Resolve `from <level dots><dotted> import ...` relative to `context`."""
        base = context.directory
        for _ in range(level - 1):
            base = os.path.dirname(base)
        parts = dotted.split(".") if dotted else []
        path = self._find_local(base, parts) if parts else _package_init(base)
        if not path:
            return None
        name = ".".join(p for p in [os.path.basename(base)] + parts if p)
        context = self.context_for_file(path, name)
        return LocalModule(context) if context else None

    def import_module(self, context, dotted, level=0):
        if level:
            return self.import_relative(context, dotted, level)
        return self.import_absolute(dotted)

    def local_submodule(self, module_value, name):
        """A submodule `name` of a local package, if such a file exists."""
        context = module_value.context
        if not context.is_package:
            return None
        path = self._find_local(context.directory, [name])
        if not path:
            return None
        sub = self.context_for_file(path, f"{context.name}.{name}")
        return LocalModule(sub) if sub else None

    def runtime_submodule(self, module_value, name):
        if not hasattr(module_value.obj, "__path__"):
            return None
        return self._import_runtime(f"{module_value.obj.__name__}.{name}")

    @staticmethod
    def _find_local(base, parts):
        directory = base
        for part in parts[:-1]:
            directory = os.path.join(directory, part)
            if not os.path.isdir(directory):
                return None
        last = os.path.join(directory, parts[-1])
        if os.path.isfile(last + ".py"):
            return last + ".py"
        return _package_init(last)

    def _import_runtime(self, dotted):
        if dotted not in self._runtime:
            module = None
            try:
                with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
                    warnings.simplefilter("ignore")
                    module = importlib.import_module(dotted)
            except BaseException:  # importing arbitrary modules may fail in any way
                module = None
            self._runtime[dotted] = RuntimeModule(module) if module is not None else None
        return self._runtime[dotted]


def _package_init(directory):
    init = os.path.join(directory, "__init__.py")
    return init if os.path.isfile(init) else None
