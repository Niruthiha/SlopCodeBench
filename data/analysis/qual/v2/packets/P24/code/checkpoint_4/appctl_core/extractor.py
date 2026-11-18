"""Archive extraction.

Secret: which archive types are recognised, which runtime facilities are
used to unpack them (and the fallback when the built-in tar.gz support
fails), and how unpacked files are merged into an existing directory.
"""

import os
import shutil
import tempfile

from . import messages as _messages
from . import process
from .errors import CliError

_ZIP = ".zip"
_TAR_GZ = ".tar.gz"


def archive_type(path):
    """``"zip"``, ``"tar.gz"`` or ``None`` for an unsupported file name."""
    name = str(path).lower()
    if name.endswith(_TAR_GZ):
        return "tar.gz"
    if name.endswith(_ZIP):
        return "zip"
    return None


def validate(archive):
    """Raise ``CliError`` unless ``archive`` is an existing supported archive."""
    if archive_type(archive) is None:
        raise CliError(_messages.unsupported_archive())
    if not os.path.isfile(archive):
        raise CliError(_messages.archive_not_found(archive))


def _reason(exc):
    return getattr(exc, "strerror", None) or str(exc) or type(exc).__name__


def _unpack_zip(archive, target):
    try:
        import zipfile
    except ImportError:
        raise CliError(_messages.zip_unavailable()) from None
    try:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(target)
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError,
            NotImplementedError, EOFError) as exc:
        raise CliError(_messages.archive_extraction_failed(archive, _reason(exc))) from None


def _unpack_tar_gz(archive, target, out):
    try:
        import tarfile
    except ImportError:
        tarfile = None
    if tarfile is not None:
        try:
            with tarfile.open(archive, "r:gz") as bundle:
                if hasattr(tarfile, "data_filter"):
                    bundle.extractall(target, filter="data")
                else:
                    bundle.extractall(target)
            return
        except (tarfile.TarError, OSError, EOFError, ValueError) as exc:
            reason = _reason(exc)
    else:
        reason = "tarfile is not available"
    out.warning(_messages.tarfile_fallback(reason))
    _reset(target)
    tar = shutil.which("tar")
    if tar is None:
        raise CliError(_messages.tar_unavailable())
    result = process.run([tar, "xzf", archive, "-C", target], out=out)
    if not result.succeeded:
        lines = result.stderr.strip().splitlines()
        raise CliError(_messages.archive_extraction_failed(
            archive, lines[0] if lines else f"tar exited with code {result.return_code}"))


def _reset(directory):
    shutil.rmtree(directory, ignore_errors=True)
    os.makedirs(directory, exist_ok=True)


def _writable(path):
    return os.access(path, os.W_OK)


def _copy_file(source, dest):
    if os.path.islink(source):
        os.symlink(os.readlink(source), dest)
    else:
        shutil.copyfile(source, dest)
        shutil.copymode(source, dest)


def copy_overwrite_files(source, dest, out):
    """Copy the tree below ``source`` into ``dest``, overwriting writable
    files. Every file that cannot be copied is reported as a warning; once
    all files have been processed a ``CliError`` is raised if any failed."""
    failed = []

    def walk(directory, relative):
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            return
        for name in names:
            src = os.path.join(directory, name)
            rel = f"{relative}/{name}" if relative else name
            dst = os.path.join(dest, *rel.split("/"))
            if os.path.isdir(src) and not os.path.islink(src):
                if not os.path.isdir(dst):
                    try:
                        os.makedirs(dst)
                    except OSError:
                        failed.append(rel)
                        out.warning(_messages.unable_to_copy(rel))
                        continue
                walk(src, rel)
                continue
            exists = os.path.lexists(dst)
            try:
                if exists and (os.path.isdir(dst) or not _writable(dst)):
                    raise PermissionError(rel)
                if exists and os.path.islink(dst) != os.path.islink(src):
                    os.unlink(dst)
                elif exists and os.path.islink(src):
                    os.unlink(dst)
                _copy_file(src, dst)
            except OSError:
                failed.append(rel)
                out.warning(_messages.unable_to_copy(rel))

    os.makedirs(dest, exist_ok=True)
    walk(source, "")
    if failed:
        raise CliError(_messages.overwrite_failed())


def extract(archive, dest, out):
    """Extract a ``.zip`` or ``.tar.gz`` ``archive`` into directory ``dest``."""
    kind = archive_type(archive)
    if kind is None:
        raise CliError(_messages.unsupported_archive())
    validate(archive)
    staging = tempfile.mkdtemp(prefix="appctl-extract-")
    try:
        if kind == "zip":
            _unpack_zip(archive, staging)
        else:
            _unpack_tar_gz(archive, staging, out)
        copy_overwrite_files(staging, dest, out)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
