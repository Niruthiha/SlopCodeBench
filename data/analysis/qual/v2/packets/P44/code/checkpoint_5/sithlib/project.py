"""Enumerating the Python source files of a project."""
import os

_SKIPPED_DIRECTORIES = {"__pycache__", "node_modules", "site-packages"}


def project_files(root):
    """Absolute paths of the `.py` files under `root`, in a stable order.

    Hidden directories, caches and virtual environments are skipped.
    """
    root = os.path.abspath(root)
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = sorted(
            name for name in subdirectories
            if not name.startswith(".") and name not in _SKIPPED_DIRECTORIES
            and not os.path.isfile(os.path.join(directory, name, "pyvenv.cfg")))
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(directory, name)
