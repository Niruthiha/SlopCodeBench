"""Module location.

Secret: how an imported module name is found — first as a source file or
package in the project directory, then as a type stub (``.pyi``) standing
alone, otherwise by importing a standard library module at runtime (with its
side effects contained) — where the stub of a source module is looked for,
how the module names importable from a place are enumerated, and which files
make up the project.
"""

import contextlib
import importlib
import io
import os
import pkgutil
import sys
import sysconfig

SOURCE = "source"  # a ``.py`` file, or a ``.pyi`` stub without one
RUNTIME = "runtime"
DIRECTORY = "directory"


class Located:
    """Where a module lives: a source file, a bare directory, or a live module."""

    def __init__(self, how, path=None, module=None):
        self.how = how
        self.path = path
        self.module = module


class ModuleLocator:
    def __init__(self, project_dir):
        self._project_dir = os.path.abspath(project_dir)
        self._runtime_cache = {}

    def locate(self, dotted, level=0, importer_path=None):
        """Locate ``dotted`` (relative to ``importer_path`` when ``level`` > 0)."""
        parts = [p for p in dotted.split(".") if p] if dotted else []
        if level > 0:
            base = self.relative_base(level, importer_path)
            return self._locate_in(base, parts, stubs=True) if base is not None else None
        if not parts:
            return None
        namespace = None
        for root in self.search_roots(importer_path):
            found = self._locate_in(root, parts)
            if found is not None and found.how == SOURCE:
                return found
            namespace = namespace or found
        if namespace is not None and _holds_python(namespace.path):
            return namespace
        for root in self.search_roots(importer_path) + [self.stubs_dir()]:
            found = self._locate_in(root, parts, stubs=True)
            if found is not None and found.how == SOURCE:
                return found
        module = self._import_runtime(".".join(parts))
        if module is not None:
            return Located(RUNTIME, module=module)
        return namespace

    def relative_base(self, level, importer_path):
        """Directory a relative import of ``level`` dots starts from, or None
        when it would leave the project."""
        base = os.path.dirname(os.path.abspath(importer_path or self._project_dir))
        for _ in range(level - 1):
            base = os.path.dirname(base)
        if base != self._project_dir and not base.startswith(
                self._project_dir.rstrip(os.sep) + os.sep):
            return None
        return base

    def stubs_dir(self):
        return os.path.join(self._project_dir, "stubs")

    def stub_for(self, path):
        """The ``.pyi`` stub giving type information for source file ``path``, or None."""
        path = os.path.abspath(path)
        if not path.endswith(".py"):
            return None
        adjacent = path + "i"
        if os.path.isfile(adjacent):
            return adjacent
        relative = os.path.relpath(path, self._project_dir)
        if relative.startswith(os.pardir + os.sep) or os.path.isabs(relative):
            return None
        parts = relative[:-3].split(os.sep)
        if parts[-1] == "__init__":
            parts.pop()
        if not parts:
            return None
        base = os.path.join(self.stubs_dir(), *parts)
        for candidate in (base + ".pyi", os.path.join(base, "__init__.pyi")):
            if os.path.isfile(candidate):
                return candidate
        return None

    def source_for(self, stub_path):
        """The source file that the ``.pyi`` stub at ``stub_path`` describes, or None."""
        stub_path = os.path.abspath(stub_path)
        adjacent = stub_path[:-1]
        if os.path.isfile(adjacent):
            return adjacent
        relative = os.path.relpath(stub_path, self.stubs_dir())
        if relative.startswith(os.pardir + os.sep) or os.path.isabs(relative):
            return None
        parts = relative[:-4].split(os.sep)
        if parts[-1] == "__init__":
            parts.pop()
        found = self._locate_in(self._project_dir, parts) if parts else None
        if found is None or found.how != SOURCE or self.stub_for(found.path) != stub_path:
            return None
        return found.path

    def search_roots(self, importer_path=None):
        roots = [self._project_dir]
        if importer_path:
            own = os.path.dirname(os.path.abspath(importer_path))
            if own not in roots:
                roots.append(own)
        return roots

    def top_level_names(self, importer_path=None):
        """Names of the modules ``import <name>`` can find."""
        names = set()
        for root in self.search_roots(importer_path):
            names.update(directory_module_names(root))
        names.update(stdlib_names())
        return names

    def locate_in_directory(self, directory, name):
        """Locate submodule ``name`` of the package stored in ``directory``."""
        return self._locate_in(directory, [name])

    def _locate_in(self, base, parts, stubs=False):
        """With ``stubs``, ``.pyi`` files stand in for missing ``.py`` files."""
        suffixes = (".py", ".pyi") if stubs else (".py",)
        path = base
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            package = os.path.join(path, part)
            regular = any(os.path.isfile(os.path.join(package, "__init__" + suffix))
                          for suffix in suffixes)
            module = [package + s for s in suffixes if os.path.isfile(package + s)]
            if os.path.isdir(package) and (regular or not module):
                if last:
                    return self._package(package, suffixes)
                path = package
                continue
            if last and module:
                return Located(SOURCE, path=module[0])
            return None
        return self._package(path, suffixes)

    @staticmethod
    def _package(directory, suffixes=(".py",)):
        for suffix in suffixes:
            init = os.path.join(directory, "__init__" + suffix)
            if os.path.isfile(init):
                return Located(SOURCE, path=init)
        return Located(DIRECTORY, path=directory)

    def _import_runtime(self, name):
        if name in self._runtime_cache:
            return self._runtime_cache[name]
        if not _is_stdlib(name):
            self._runtime_cache[name] = None
            return None
        module = None
        saved_path = list(sys.path)
        sys.path[:] = [p for p in sys.path
                       if p and os.path.abspath(p) not in (self._project_dir, _TOOL_DIR)]
        try:
            with _silenced_descriptors(), contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                module = importlib.import_module(name)
        except BaseException:  # noqa: B902 - arbitrary import code may do anything
            module = None
        finally:
            sys.path[:] = saved_path
        self._runtime_cache[name] = module
        return module


@contextlib.contextmanager
def _silenced_descriptors():
    """Route OS-level stdout/stderr to the null device (for C extensions)."""
    saved = []
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        devnull = os.open(os.devnull, os.O_WRONLY)
        for fd in (1, 2):
            saved.append((fd, os.dup(fd)))
            os.dup2(devnull, fd)
        os.close(devnull)
    except (OSError, ValueError, AttributeError):
        pass
    try:
        yield
    finally:
        for fd, copy in saved:
            os.dup2(copy, fd)
            os.close(copy)


_TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Standard library modules never imported for analysis (they act on import).
_UNSAFE = ("antigravity", "this", "__main__", "idlelib.idle", "idlelib.__main__")


def _is_stdlib(name):
    if name in _UNSAFE or name.endswith(".__main__"):
        return False
    top = name.split(".")[0]
    return top in getattr(sys, "stdlib_module_names", ()) or top in sys.builtin_module_names


_STDLIB_NAMES = None


def stdlib_names():
    """Top-level standard library modules available in this runtime."""
    global _STDLIB_NAMES
    if _STDLIB_NAMES is None:
        known = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names)
        found = set(sys.builtin_module_names)
        directories = []
        for key in ("stdlib", "platstdlib"):
            path = sysconfig.get_paths().get(key)
            if path:
                directories += [path, os.path.join(path, "lib-dynload")]
        directories += [os.path.dirname(os.__file__)]
        directories = [d for d in dict.fromkeys(directories) if os.path.isdir(d)]
        try:
            found.update(info.name for info in pkgutil.iter_modules(directories))
        except (OSError, ImportError):
            pass
        _STDLIB_NAMES = {n for n in found & known if n not in _UNSAFE}
    return set(_STDLIB_NAMES)


def _holds_python(directory, depth=3):
    """Whether a namespace directory contains Python sources (near the top)."""
    try:
        entries = os.listdir(directory)
    except OSError:
        return False
    for entry in entries:
        path = os.path.join(directory, entry)
        if entry.endswith(".py") and os.path.isfile(path):
            return True
        if depth > 1 and entry.isidentifier() and os.path.isdir(path) \
                and _holds_python(path, depth - 1):
            return True
    return False


def directory_module_names(directory):
    """Modules and packages (regular or namespace) stored directly in ``directory``."""
    names = set()
    try:
        entries = os.listdir(directory)
    except OSError:
        return names
    for entry in entries:
        path = os.path.join(directory, entry)
        if entry.endswith(".py") and os.path.isfile(path):
            name = entry[:-3]
        elif os.path.isdir(path):
            name = entry
        else:
            continue
        if name.isidentifier() and name not in ("__init__", "__pycache__", "__main__"):
            names.add(name)
    return names


def runtime_submodule_names(module):
    """Submodules of a live package."""
    path = getattr(module, "__path__", None)
    if not path:
        return set()
    try:
        return {info.name for info in pkgutil.iter_modules(list(path))
                if info.name.isidentifier() and info.name != "__main__"}
    except (OSError, ImportError, TypeError):
        return set()


_SKIPPED_DIRECTORIES = ("__pycache__", "node_modules", "site-packages")


def project_files(root, suffix=".py"):
    """Files ending in ``suffix`` below ``root`` (hidden and cache directories
    skipped), sorted."""
    found = []
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = sorted(d for d in subdirectories
                                   if not d.startswith(".") and d not in _SKIPPED_DIRECTORIES)
        for name in files:
            if name.endswith(suffix) and not name.startswith("."):
                found.append(os.path.join(directory, name))
    return sorted(found)
