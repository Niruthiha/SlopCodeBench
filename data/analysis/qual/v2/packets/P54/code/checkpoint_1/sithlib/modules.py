"""Module location.

Secret: how an imported module name is found — first as a source file or
package in the project directory, otherwise by importing an installed module
at runtime (with its side effects contained).
"""

import contextlib
import importlib
import io
import os
import sys

SOURCE = "source"
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
            base = os.path.dirname(os.path.abspath(importer_path or self._project_dir))
            for _ in range(level - 1):
                base = os.path.dirname(base)
            return self._locate_in(base, parts)
        if not parts:
            return None
        roots = [self._project_dir]
        if importer_path:
            own = os.path.dirname(os.path.abspath(importer_path))
            if own not in roots:
                roots.append(own)
        namespace = None
        for root in roots:
            found = self._locate_in(root, parts)
            if found is not None and found.how == SOURCE:
                return found
            namespace = namespace or found
        module = self._import_runtime(".".join(parts))
        if module is not None:
            return Located(RUNTIME, module=module)
        return namespace

    def locate_in_directory(self, directory, name):
        """Locate submodule ``name`` of the package stored in ``directory``."""
        return self._locate_in(directory, [name])

    def _locate_in(self, base, parts):
        path = base
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            package = os.path.join(path, part)
            if os.path.isdir(package):
                if last:
                    return self._package(package)
                path = package
                continue
            if last and os.path.isfile(package + ".py"):
                return Located(SOURCE, path=package + ".py")
            return None
        return self._package(path)

    @staticmethod
    def _package(directory):
        init = os.path.join(directory, "__init__.py")
        if os.path.isfile(init):
            return Located(SOURCE, path=init)
        return Located(DIRECTORY, path=directory)

    def _import_runtime(self, name):
        if name in self._runtime_cache:
            return self._runtime_cache[name]
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
