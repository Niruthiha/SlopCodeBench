"""Module contexts and import resolution (project files first, then the standard library)."""
import ast
import contextlib
import importlib
import importlib.util
import io
import os
import pkgutil
import sys
import warnings

from .parsing import parse_tolerant
from .scopes import ScopeBuilder
from .source import read_text
from .errors import SithError
from .values import LocalModule, RuntimeModule

STDLIB_NAMES = frozenset(sys.stdlib_module_names) | frozenset(sys.builtin_module_names)


class ModuleContext:
    """A parsed Python module together with its scope tree.

    A namespace package (a directory without `__init__.py`) is a context
    without a path and with an empty syntax tree.
    """

    def __init__(self, path, name, tree, text="", directory=None):
        self.path = os.path.abspath(path) if path else None
        if directory is not None:
            self.directory = os.path.abspath(directory)
        else:
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
    def is_namespace(self):
        return self.path is None

    @property
    def is_package(self):
        return self.is_namespace or os.path.basename(self.path) == "__init__.py"

    @property
    def location(self):
        """The file of the module, or the directory of a namespace package."""
        return self.path or self.directory

    def scope_of(self, node):
        return self.scope_by_node.get(id(node))

    def binding_of(self, node):
        """The binding created for a name node (or def/class/except node), if any."""
        return self.binding_by_target.get(id(node))


class Importer:
    """Resolves module names to values: project files first, then the standard library.

    Anything else (third-party packages, missing modules) is unresolvable.
    """

    def __init__(self, project_dir):
        self.project_dir = os.path.abspath(project_dir)
        self._contexts = {}
        self._namespaces = {}
        self._runtime = {}

    def register(self, context):
        if context.path:
            self._contexts[context.path] = context

    def module_name(self, location):
        """Dotted name of the module at `location` (file or directory), relative to the root."""
        try:
            relative = os.path.relpath(os.path.abspath(location), self.project_dir)
        except ValueError:  # another drive (Windows)
            relative = os.pardir
        if relative == os.curdir:
            return ""
        if relative == os.pardir or relative.startswith(os.pardir + os.sep):
            relative = os.path.basename(location)
        stem = os.path.splitext(relative)[0] if os.path.isfile(location) else relative
        parts = [p for p in stem.split(os.sep) if p]
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    def context_for_file(self, path, name=None):
        path = os.path.abspath(path)
        if path not in self._contexts:
            try:
                text = read_text(path)
            except SithError:
                return None
            if name is None:
                name = self.module_name(path)
            self._contexts[path] = ModuleContext(path, name, parse_tolerant(text), text)
        return self._contexts[path]

    def namespace_for(self, directory):
        directory = os.path.abspath(directory)
        if directory not in self._namespaces:
            self._namespaces[directory] = ModuleContext(
                None, self.module_name(directory), ast.Module(body=[], type_ignores=[]),
                directory=directory)
        return self._namespaces[directory]

    def _local(self, found):
        """A LocalModule for a `_locate` result."""
        if found is None:
            return None
        kind, location = found
        if kind == "namespace":
            return LocalModule(self.namespace_for(location))
        context = self.context_for_file(location)
        return LocalModule(context) if context else None

    # -- absolute and relative imports -------------------------------------------

    def import_absolute(self, dotted):
        """Resolve `import dotted` to a module value, or None."""
        if not dotted:
            return None
        parts = dotted.split(".")
        module = self.top_level(parts[0])
        if isinstance(module, RuntimeModule) and len(parts) > 1:
            return self._import_runtime(dotted)
        for part in parts[1:]:
            if module is None:
                return None
            module = self.submodule(module, part)
        return module

    def top_level(self, name):
        """The top-level module `name`: a project module or package, else stdlib."""
        found = _locate(self.project_dir, name, namespace=False)
        if found:
            return self._local(found)
        if name in STDLIB_NAMES:
            module = self._import_runtime(name)
            if module is not None:
                return module
        return self._local(_locate(self.project_dir, name, namespace=True))

    def submodule(self, module, name):
        """The submodule `name` of a package value, or None."""
        if isinstance(module, LocalModule):
            return self.local_submodule(module, name)
        if isinstance(module, RuntimeModule):
            return self.runtime_submodule(module, name)
        return None

    def import_relative(self, context, dotted, level):
        """Resolve `from <level dots><dotted> import ...` relative to `context`."""
        base = context.directory
        for _ in range(level - 1):
            base = os.path.dirname(base)
        if not self.within_project(base):
            return None
        module = self.package_at(base)
        for part in (dotted.split(".") if dotted else []):
            if module is None:
                return None
            module = self.local_submodule(module, part)
        return module

    def import_module(self, context, dotted, level=0):
        if level:
            return self.import_relative(context, dotted, level)
        return self.import_absolute(dotted)

    def within_project(self, directory):
        directory = os.path.abspath(directory)
        root = self.project_dir
        return directory == root or directory.startswith(root.rstrip(os.sep) + os.sep)

    def package_at(self, directory):
        """The package whose directory is `directory` (regular or namespace)."""
        init = _package_init(directory)
        if init:
            context = self.context_for_file(init)
            return LocalModule(context) if context else None
        if os.path.isdir(directory):
            return LocalModule(self.namespace_for(directory))
        return None

    def local_submodule(self, module_value, name):
        """A submodule `name` of a local package, if such a file or directory exists."""
        context = module_value.context
        if not context.is_package or not name:
            return None
        found = _locate(context.directory, name, namespace=False)
        return self._local(found or _locate(context.directory, name, namespace=True))

    def runtime_submodule(self, module_value, name):
        if not hasattr(module_value.obj, "__path__"):
            return None
        return self._import_runtime(f"{module_value.obj.__name__}.{name}")

    # -- listing modules (import completion) ------------------------------------

    def top_level_names(self):
        """Names of every importable top-level module."""
        return set(_module_names(self.project_dir)) | available_stdlib()

    def submodule_names(self, module):
        """Names of the submodules of a package value."""
        if isinstance(module, LocalModule):
            if not module.context.is_package:
                return set()
            return set(_module_names(module.context.directory))
        if isinstance(module, RuntimeModule):
            paths = getattr(module.obj, "__path__", None)
            if paths is None:
                return set()
            try:
                return {info.name for info in pkgutil.iter_modules(list(paths))}
            except Exception:
                return set()
        return set()

    def _import_runtime(self, dotted):
        if dotted.split(".")[0] not in STDLIB_NAMES:
            return None
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


_STDLIB_AVAILABLE = None


def available_stdlib():
    """Top-level standard library modules that exist in this runtime."""
    global _STDLIB_AVAILABLE
    if _STDLIB_AVAILABLE is None:
        names = set()
        for name in STDLIB_NAMES:
            if name == "__main__":
                continue
            try:
                if name in sys.modules or importlib.util.find_spec(name) is not None:
                    names.add(name)
            except Exception:
                continue
        _STDLIB_AVAILABLE = names
    return _STDLIB_AVAILABLE


def _locate(directory, name, namespace):
    """("file", path) or ("namespace", directory) for module `name` inside `directory`.

    Regular packages win over modules; namespace packages are only
    considered when `namespace` is true.
    """
    if not name or not os.path.isdir(directory):
        return None
    candidate = os.path.join(directory, name)
    if namespace:
        if os.path.isdir(candidate) and name.isidentifier():
            return "namespace", candidate
        return None
    init = _package_init(candidate)
    if init:
        return "file", init
    if os.path.isfile(candidate + ".py"):
        return "file", candidate + ".py"
    return None


def _module_names(directory):
    """Names of the modules and packages (including namespace packages) in `directory`."""
    try:
        entries = os.listdir(directory)
    except OSError:
        return []
    names = []
    for entry in entries:
        path = os.path.join(directory, entry)
        if entry.endswith(".py") and os.path.isfile(path):
            stem = entry[:-3]
            if stem.isidentifier() and stem != "__init__":
                names.append(stem)
        elif os.path.isdir(path) and entry.isidentifier() and entry != "__pycache__":
            names.append(entry)
    return names


def _package_init(directory):
    init = os.path.join(directory, "__init__.py")
    return init if os.path.isfile(init) else None
