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

from . import options
from .parsing import parse_tolerant
from .scopes import ScopeBuilder
from .source import read_text
from .errors import SithError
from .values import LocalModule, RuntimeModule

STDLIB_NAMES = frozenset(sys.stdlib_module_names) | frozenset(sys.builtin_module_names)
# Directory (relative to the project root) holding stub files for project or external modules.
STUB_DIRECTORY = "stubs"


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
        return self.is_namespace or os.path.basename(self.path) in ("__init__.py", "__init__.pyi")

    @property
    def is_stub(self):
        """True for a `.pyi` type stub."""
        return bool(self.path) and self.path.endswith(".pyi")

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

    Project files are found in the roots of the search path (see
    `options.SearchPath`), by default the project directory.  Anything else
    (third-party packages, missing modules) is unresolvable.
    """

    def __init__(self, project_dir, search_path=None):
        self.project_dir = os.path.abspath(project_dir)
        self.stub_dir = os.path.join(self.project_dir, STUB_DIRECTORY)
        if search_path is None:
            search_path = options.current().search_path(self.project_dir)
        self.early_roots = search_path.early
        self.late_roots = search_path.late
        self.roots = search_path.early + search_path.late
        self.named_roots = search_path.named
        self._contexts = {}
        self._namespaces = {}
        self._runtime = {}
        self._stubs = {}
        self._sources = {}

    def register(self, context):
        if context.path:
            self._contexts[context.path] = context

    def module_name(self, location):
        """Dotted name of the module at `location` (file or directory), relative to the root.

        Stubs in the project's stub directory are named relative to that directory.
        """
        base = self.naming_base(location) or self.project_dir
        if _within(location, self.stub_dir) and (location.endswith(".pyi") or os.path.isdir(location)):
            base = self.stub_dir
        try:
            relative = os.path.relpath(os.path.abspath(location), base)
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

    def naming_base(self, location):
        """The innermost configured root (or the project root) containing `location`, if any."""
        containing = [root for root in self.named_roots if _within(location, root)]
        return max(containing, key=len) if containing else None

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
        found = _locate_in(self.early_roots, name, namespace=False)
        if found:
            return self._local(found)
        if name in STDLIB_NAMES:
            module = self._import_runtime(name)
            if module is not None:
                return module
        found = _locate_in(self.late_roots + [self.stub_dir], name, namespace=False)
        if found:
            return self._local(found)
        return self._local(_locate_in(self.roots, name, namespace=True))

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
        return any(_within(directory, root) for root in [self.project_dir] + self.roots)

    # -- stubs ----------------------------------------------------------------------

    def stub_for(self, context):
        """The parsed `.pyi` stub giving type information for the module `context`, or None.

        An adjacent `foo.pyi` wins over `stubs/foo.pyi` and `stubs/foo/__init__.pyi`.
        """
        if context is None or not context.path or context.is_stub:
            return None
        if context.path not in self._stubs:
            self._stubs[context.path] = None
            path = self._stub_path(context.path)
            stub = self.context_for_file(path) if path else None
            if stub is not None:
                self._sources.setdefault(stub.path, context)
            self._stubs[context.path] = stub
        return self._stubs[context.path]

    def _stub_path(self, path):
        adjacent = os.path.splitext(path)[0] + ".pyi"
        if os.path.isfile(adjacent):
            return adjacent
        name = self.module_name(path)
        if not name:
            return None
        base = os.path.join(self.stub_dir, *name.split("."))
        for candidate in (base + ".pyi", os.path.join(base, "__init__.pyi")):
            if os.path.isfile(candidate):
                return candidate
        return None

    def source_for(self, stub):
        """The `.py` module a stub describes, or None for stub-only modules."""
        if stub is None or not stub.is_stub:
            return None
        if stub.path not in self._sources:
            self._sources[stub.path] = None
            path = os.path.splitext(stub.path)[0] + ".py"
            if not os.path.isfile(path):
                path = None
                if _within(stub.path, self.stub_dir):
                    path = self._source_path(self.module_name(stub.path))
            source = self.context_for_file(path) if path else None
            if source is not None and self.stub_for(source) is not stub:
                source = None
            self._sources[stub.path] = source
        return self._sources[stub.path]

    def _source_path(self, dotted):
        if not dotted:
            return None
        for root in [self.project_dir] + self.roots:
            base = os.path.join(root, *dotted.split("."))
            for candidate in (os.path.join(base, "__init__.py"), base + ".py"):
                if os.path.isfile(candidate):
                    return candidate
        return None

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
        names = set(_module_names(self.stub_dir)) | available_stdlib()
        for root in self.roots:
            names.update(_module_names(root))
        return names

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


def _within(path, directory):
    path = os.path.abspath(path)
    directory = os.path.abspath(directory)
    return path == directory or path.startswith(directory.rstrip(os.sep) + os.sep)


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


def _locate_in(directories, name, namespace):
    """The first `_locate` result among `directories`."""
    for directory in directories:
        found = _locate(directory, name, namespace)
        if found:
            return found
    return None


def _locate(directory, name, namespace):
    """("file", path) or ("namespace", directory) for module `name` inside `directory`.

    Regular packages win over modules, and source modules over stub-only
    modules; namespace packages are only considered when `namespace` is true.
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
    for suffix in (".py", ".pyi"):
        if os.path.isfile(candidate + suffix):
            return "file", candidate + suffix
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
        if entry.endswith((".py", ".pyi")) and os.path.isfile(path):
            stem = os.path.splitext(entry)[0]
            if stem.isidentifier() and stem != "__init__":
                names.append(stem)
        elif os.path.isdir(path) and entry.isidentifier() and entry != "__pycache__":
            names.append(entry)
    return names


def _package_init(directory):
    for name in ("__init__.py", "__init__.pyi"):
        init = os.path.join(directory, name)
        if os.path.isfile(init):
            return init
    return None
