"""Filesystem cache for downloaded files and intermediate data."""

import hashlib
import os
import re
import shutil
import sys
import tempfile
import time
from urllib.parse import urlsplit

from .config_loader import ROOT_DIR_ENV, root_dir

CACHE_DIR_ENV = "APPCTL_CACHE_DIR"
CACHE_TTL_ENV = "APPCTL_CACHE_TTL"
CACHE_MAX_SIZE_ENV = "APPCTL_CACHE_MAX_SIZE"

DEFAULT_TTL = 180 * 86400               # 180 days, in seconds
DEFAULT_MAX_SIZE = 300 * 1024 * 1024    # 300 MiB, in bytes
MAX_SEGMENT_LENGTH = 120
HASH_LENGTH = 12

_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def cache_dir(environ=None):
    """``APPCTL_CACHE_DIR``, otherwise ``<APPCTL_ROOT_DIR>/.cache/``."""
    environ = os.environ if environ is None else environ
    value = environ.get(CACHE_DIR_ENV)
    if value:
        return value
    return os.path.join(root_dir(environ), ".cache") + os.sep


def _int_setting(environ, name, default):
    try:
        value = int(str(environ.get(name, "")).strip())
    except ValueError:
        return default
    return value if value >= 0 else default


def _digest(text):
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:HASH_LENGTH]


def _sanitize_segment(segment):
    """Make one path segment filesystem-safe; altered segments get a hash suffix."""
    safe = _UNSAFE_RE.sub("-", segment)
    if safe in ("", ".", ".."):
        safe = safe.replace(".", "-") or "-"
    if safe != segment or len(safe) > MAX_SEGMENT_LENGTH:
        safe = f"{safe[:MAX_SEGMENT_LENGTH]}-{_digest(segment)}"
    return safe


def sanitize_key(key):
    """Map a cache key to a deterministic, filesystem-safe relative path.

    URL keys are stored under ``misc/<scheme>-<host>[-<port>]/<path>[-<query>]``;
    other keys keep their ``/``-separated structure. Any segment that has to be
    altered gets a hash of its original value appended, so distinct keys do not
    collide.
    """
    key = str(key).strip()
    if _URL_SCHEME_RE.match(key):
        url = urlsplit(key)
        host = url.hostname or ""
        try:
            port = url.port
        except ValueError:
            port = None
        location = f"{url.scheme}-{host}" + (f"-{port}" if port else "")
        resource = url.path.lstrip("/") + (f"-{url.query}" if url.query else "")
        parts = ["misc", location] + [p for p in resource.split("/") if p]
        if len(parts) == 2:
            parts.append("-")
    else:
        parts = [p for p in key.replace("\\", "/").split("/") if p]
    if not parts:
        return _sanitize_segment("")
    return "/".join(_sanitize_segment(part) for part in parts)


def _warn(output, text):
    if output is not None:
        output.warning(text)
    else:
        print(f"Warning: {text}", file=sys.stderr)


class FileCache:
    """Key/value file store with a TTL and a maximum total size."""

    def __init__(self, root, ttl=DEFAULT_TTL, max_size=DEFAULT_MAX_SIZE, output=None):
        self.configured_root = str(root)
        self.root = os.path.join(self.configured_root, "")
        self.ttl = int(ttl)
        self.max_size = int(max_size)
        self.output = output
        self.enabled = self._ensure_dir_exists(self.root, self.configured_root)

    def _ensure_dir_exists(self, directory, label=None):
        if os.path.isdir(directory):
            return True
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            reason = exc.strerror or exc
            _warn(self.output, f"Failed to create directory '{label or directory}': {reason}.")
            return False
        return True

    def is_enabled(self):
        return self.enabled

    def get_root(self):
        return self.root

    def filename(self, key):
        return os.path.join(self.root, *sanitize_key(key).split("/"))

    # -- reading -----------------------------------------------------------

    def _is_expired(self, mtime, ttl, now=None):
        ttl = self.ttl if ttl is None else int(ttl)
        return ttl > 0 and mtime + ttl < (time.time() if now is None else now)

    def has(self, key, ttl=None):
        """Path of a fresh entry for ``key``; expired entries are deleted. ``False`` on a miss."""
        if not self.enabled:
            return False
        path = self.filename(key)
        try:
            info = os.stat(path)
        except OSError:
            return False
        if not os.path.isfile(path):
            return False
        if self._is_expired(info.st_mtime, ttl):
            self._unlink(path)
            return False
        return path

    def read(self, key, ttl=None, binary=False):
        """Cached content for ``key``, or ``False`` on a miss."""
        path = self.has(key, ttl)
        if not path:
            return False
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            return False
        self._touch_access(path)
        return data if binary else data.decode("utf-8", "replace")

    def export(self, key, target, ttl=None):
        """Copy the entry for ``key`` to ``target``; ``False`` on a miss."""
        path = self.has(key, ttl)
        if not path:
            return False
        try:
            directory = os.path.dirname(os.path.abspath(target))
            os.makedirs(directory, exist_ok=True)
            shutil.copyfile(path, target)
        except OSError:
            return False
        self._touch_access(path)
        return True

    @staticmethod
    def _touch_access(path):
        """Record a use (atime) without extending the entry's lifetime (mtime)."""
        try:
            info = os.stat(path)
            os.utime(path, (time.time(), info.st_mtime))
        except OSError:
            pass

    # -- writing -------------------------------------------------------------

    def write(self, key, contents):
        """Store ``contents`` (str or bytes) for ``key``; return the success."""
        if not self.enabled:
            return False
        data = contents.encode("utf-8") if isinstance(contents, str) else bytes(contents)
        return self._store(key, lambda handle: handle.write(data))

    def import_file(self, key, source):
        """Store a copy of the file at ``source`` for ``key``; return the success."""
        if not self.enabled or not os.path.isfile(source) or not os.access(source, os.R_OK):
            return False

        def copy(handle):
            with open(source, "rb") as src:
                shutil.copyfileobj(src, handle)
        return self._store(key, copy)

    def _store(self, key, fill):
        path = self.filename(key)
        directory = os.path.dirname(path)
        if not self._ensure_dir_exists(directory):
            return False
        try:
            fd, temp = tempfile.mkstemp(dir=directory, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as handle:
                    fill(handle)
                os.replace(temp, path)
            except BaseException:
                self._unlink(temp)
                raise
            now = time.time()
            os.utime(path, (now, now))
        except OSError:
            return False
        return True

    def remove(self, key):
        if not self.enabled:
            return False
        path = self.filename(key)
        return os.path.isfile(path) and self._unlink(path)

    # -- maintenance -----------------------------------------------------------

    def _entries(self):
        """``(path, stat)`` of every cached file, sorted by path."""
        entries = []
        for directory, dirnames, filenames in os.walk(self.root):
            dirnames.sort()
            for name in sorted(filenames):
                path = os.path.join(directory, name)
                try:
                    info = os.lstat(path)
                except OSError:
                    continue
                if os.path.isfile(path) and not os.path.islink(path):
                    entries.append((path, info))
        return entries

    def clean(self, now=None):
        """Delete expired entries, then evict least recently used ones until under the size limit."""
        if not self.enabled:
            return False
        now = time.time() if now is None else now
        live = []
        for path, info in self._entries():
            if self._is_expired(info.st_mtime, None, now):
                self._unlink(path)
            else:
                live.append((path, info))
        if self.max_size > 0:
            # Most recently used first; the path breaks ties deterministically.
            live.sort(key=lambda e: (-max(e[1].st_atime, e[1].st_mtime), e[0]))
            total = 0
            for path, info in live:
                if total + info.st_size <= self.max_size:
                    total += info.st_size
                else:
                    self._unlink(path)
        self._remove_empty_dirs()
        return True

    def clear(self):
        """Delete every cached file."""
        if not self.enabled:
            return False
        for path, _ in self._entries():
            self._unlink(path)
        self._remove_empty_dirs()
        return True

    def _remove_empty_dirs(self):
        for directory, _, _ in sorted(os.walk(self.root), key=lambda w: w[0], reverse=True):
            if os.path.normpath(directory) == os.path.normpath(self.root):
                continue
            try:
                os.rmdir(directory)
            except OSError:
                pass

    @staticmethod
    def _unlink(path):
        try:
            os.unlink(path)
        except OSError:
            return False
        return True


_cache = None


def get_cache(environ=None, output=None):
    """The process-wide cache for the current configuration."""
    global _cache
    environ = os.environ if environ is None else environ
    root = cache_dir(environ)
    ttl = _int_setting(environ, CACHE_TTL_ENV, DEFAULT_TTL)
    max_size = _int_setting(environ, CACHE_MAX_SIZE_ENV, DEFAULT_MAX_SIZE)
    current = _cache
    if (current is None or current.root != os.path.join(root, "")
            or (current.ttl, current.max_size) != (ttl, max_size)):
        current = _cache = FileCache(root, ttl, max_size, output=output)
    return current


def reset_cache():
    global _cache
    _cache = None


__all__ = ["CACHE_DIR_ENV", "DEFAULT_MAX_SIZE", "DEFAULT_TTL", "FileCache", "ROOT_DIR_ENV",
           "cache_dir", "get_cache", "reset_cache", "sanitize_key"]
