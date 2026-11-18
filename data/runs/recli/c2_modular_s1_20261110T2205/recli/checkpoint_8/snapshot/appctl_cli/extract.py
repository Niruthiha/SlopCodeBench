"""Extraction of ``.zip`` and ``.tar.gz`` archives into a directory."""

import os
import shutil
import stat
import tarfile
import tempfile

from .errors import AppctlError
from .process import run_command

try:
    import zipfile
except ImportError:  # pragma: no cover - depends on the Python build
    zipfile = None

UNSUPPORTED_MESSAGE = "Extraction only supported for '.zip' and '.tar.gz' file types."


def archive_type(path):
    """``"zip"``, ``"tar.gz"`` or ``None`` for an unsupported extension."""
    name = str(path).lower()
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".tar.gz"):
        return "tar.gz"
    return None


def validate_archive(path):
    """Raise unless ``path`` names an existing archive of a supported type."""
    if path is None or path is True or path is False or str(path) == "":
        raise AppctlError("Please provide the archive to extract with --archive=<archive-path>.")
    kind = archive_type(path)
    if kind is None:
        raise AppctlError(UNSUPPORTED_MESSAGE)
    if not os.path.exists(path):
        raise AppctlError(f"Archive '{path}' does not exist.")
    if not os.path.isfile(path):
        raise AppctlError(f"Archive '{path}' is not a file.")
    if not os.access(path, os.R_OK):
        raise AppctlError(f"Archive '{path}' is not readable.")
    return kind


def _extract_zip(archive, target):
    if zipfile is None:
        raise AppctlError("Extracting a zip file requires the 'zipfile' module to be available.")
    try:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(target)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError, RuntimeError) as exc:
        raise AppctlError(f"Unable to extract '{archive}': {exc}") from exc


def _extract_tarball(archive, target, output):
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(target, filter="data")
        return
    except (tarfile.TarError, OSError, EOFError, ValueError) as exc:
        output.warning(f"Python tarfile extraction failed, falling back to 'tar xzf' ({exc}).")
    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target, exist_ok=True)
    result = run_command(["tar", "xzf", os.path.abspath(archive), "-C", target], output)
    if result.return_code != 0:
        reason = result.stderr.strip() or f"exit code {result.return_code}"
        raise AppctlError(f"Unable to extract '{archive}': {reason}")


def _is_writable(path):
    """Writable for the current user and not marked read-only."""
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return False
    return os.access(path, os.W_OK) and bool(mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def copy_overwrite_files(source, dest, output):
    """Copy the tree ``source`` into ``dest``, overwriting writable files.

    Each file that cannot be written triggers a warning; an error is raised
    once everything else has been copied.
    """
    failed = False
    for directory, dirnames, filenames in os.walk(source):
        dirnames.sort()
        relative_dir = os.path.relpath(directory, source)
        target_dir = dest if relative_dir == "." else os.path.join(dest, relative_dir)
        if not os.path.isdir(target_dir):
            try:
                os.makedirs(target_dir, exist_ok=True)
            except OSError:
                pass
        for name in sorted(filenames):
            item = os.path.join(directory, name)
            relative = name if relative_dir == "." else os.path.join(relative_dir, name)
            target = os.path.join(target_dir, name)
            exists = os.path.lexists(target)
            try:
                if exists and (os.path.isdir(target) or not _is_writable(target)):
                    raise PermissionError(target)
                if exists:
                    shutil.copyfile(item, target)
                else:
                    shutil.copy2(item, target, follow_symlinks=False)
            except OSError:
                failed = True
                output.warning(f"Unable to copy '{relative.replace(os.sep, '/')}' "
                               f"to current directory.")
    if failed:
        raise AppctlError("There was an error overwriting existing files.")


def extract_archive(archive, dest, output):
    """Extract ``archive`` (``.zip`` or ``.tar.gz``) into the directory ``dest``."""
    kind = validate_archive(archive)
    dest = os.path.abspath(dest)
    if os.path.exists(dest) and not os.path.isdir(dest):
        raise AppctlError(f"Destination '{dest}' is not a directory.")
    workdir = tempfile.mkdtemp(prefix="appctl-extract-")
    try:
        target = os.path.join(workdir, "contents")
        os.makedirs(target)
        if kind == "zip":
            _extract_zip(archive, target)
        else:
            _extract_tarball(archive, target, output)
        try:
            os.makedirs(dest, exist_ok=True)
        except OSError as exc:
            raise AppctlError(
                f"Failed to create directory '{dest}': {exc.strerror or exc}.") from exc
        copy_overwrite_files(target, dest, output)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return dest
