"""Filesystem cache for downloads and intermediate data.

Secret: where the cache directory lives, the default time-to-live and size
limit (and the environment variables overriding them), how keys are mapped
to file names, which entries count as expired, and the order in which
entries are evicted when the cache grows too large.
"""

import hashlib
import os
import re
import shutil
import time
from urllib.parse import urlsplit

from . import messages as _messages

_DIR_ENV = "APPCTL_CACHE_DIR"
_TTL_ENV = "APPCTL_CACHE_EXPIRY"
_SIZE_ENV = "APPCTL_CACHE_MAX_SIZE"
_DEFAULT_SUBDIR = ".cache"
DEFAULT_TTL = 15552000          # 180 days
DEFAULT_MAX_SIZE = 314572800    # 300 MiB
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
_MAX_PART = 200
_HASH_LENGTH = 12


def cache_dir(env, root_dir):
    """``APPCTL_CACHE_DIR`` when set, otherwise ``<root_dir>/.cache/``."""
    configured = env.get(_DIR_ENV) or ""
    if configured:
        return os.path.expanduser(configured)
    return os.path.join(root_dir, _DEFAULT_SUBDIR) + os.sep


def _int_env(env, name, default):
    try:
        value = int(str(env.get(name, "")).strip())
    except ValueError:
        return default
    return value if value >= 0 else default


def from_env(env, root_dir, warn=None):
    """The cache configured by ``env`` (TTL and size may be overridden)."""
    return FileCache(cache_dir(env, root_dir),
                     ttl=_int_env(env, _TTL_ENV, DEFAULT_TTL),
                     max_size=_int_env(env, _SIZE_ENV, DEFAULT_MAX_SIZE),
                     warn=warn)


def _digest(text):
    return hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()[:_HASH_LENGTH]


def _safe_part(part):
    """A filesystem-safe name for one key segment. Segments that are already
    safe are kept as they are; any other segment gets a digest of its
    original text appended so that distinct segments stay distinct."""
    cleaned = _UNSAFE.sub("-", part)
    if cleaned == part and part not in ("", ".", "..") and len(part) <= _MAX_PART:
        return part
    cleaned = cleaned.strip(".")[:_MAX_PART] or "-"
    return f"{cleaned}~{_digest(part)}"


def sanitize_key(key):
    """Deterministic, filesystem-safe relative path for cache ``key``.

    URLs map to ``misc/<scheme>-<host>[-<port>]/<path>[-<query>]``; other keys
    are split into directories on ``/`` and ``\\``.
    """
    key = str(key)
    url = urlsplit(key) if "://" in key else None
    if url is not None and url.scheme and url.netloc:
        host = f"{url.scheme}-{url.hostname or url.netloc}"
        if url.port:
            host += f"-{url.port}"
        tail = url.path.lstrip("/") + (f"-{url.query}" if url.query else "")
        parts = ["misc", host, tail or "-"]
    else:
        parts = [p for p in key.replace("\\", "/").split("/") if p != ""]
        if not parts:
            parts = [key]
    return "/".join(_safe_part(p) for p in parts)


class FileCache:
    """Key/value store backed by files below a root directory.

    An entry expires ``ttl`` seconds after it was last written (0 disables
    expiry). ``clean`` removes expired entries and then evicts the least
    recently used ones until the total size is at most ``max_size`` (0
    disables the limit).
    """

    def __init__(self, root, ttl=DEFAULT_TTL, max_size=DEFAULT_MAX_SIZE, warn=None):
        self.root = str(root)
        self.ttl = int(ttl)
        self.max_size = int(max_size)
        self._warn = warn
        self.enabled = self._ensure_dir(self.root)

    # --- helpers ----------------------------------------------------------

    def _warning(self, text):
        if self._warn is not None:
            self._warn(text)

    def _ensure_dir(self, directory, report=True):
        if os.path.isdir(directory):
            return True
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            if report:
                self._warning(_messages.directory_uncreatable(directory, exc))
            return False
        return True

    def is_enabled(self):
        return self.enabled

    def get_root(self):
        return self.root

    def filename(self, key):
        return os.path.join(self.root, *sanitize_key(key).split("/"))

    def _expired(self, mtime, ttl, now):
        return ttl > 0 and now - mtime > ttl

    def _effective_ttl(self, ttl):
        return self.ttl if ttl is None else int(ttl)

    def _entries(self):
        """``(path, size, recency)`` for every file, in a stable order."""
        found = []
        for directory, dirs, files in os.walk(self.root):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(directory, name)
                try:
                    info = os.lstat(path)
                except OSError:
                    continue
                found.append((path, info.st_size, info.st_mtime,
                              max(info.st_atime, info.st_mtime)))
        return found

    def _unlink(self, path):
        try:
            os.unlink(path)
            return True
        except OSError:
            return False

    def _prune_empty_dirs(self):
        for directory, _, _ in sorted(os.walk(self.root), reverse=True):
            if os.path.normpath(directory) == os.path.normpath(self.root):
                continue
            try:
                os.rmdir(directory)
            except OSError:
                pass

    # --- reading ----------------------------------------------------------

    def has(self, key, ttl=None):
        """The entry's file name when it exists and has not expired, else
        ``False``. An expired entry is deleted."""
        if not self.enabled:
            return False
        path = self.filename(key)
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            return False
        if not os.path.isfile(path):
            return False
        if self._expired(mtime, self._effective_ttl(ttl), time.time()):
            self._unlink(path)
            return False
        return path

    def read(self, key, ttl=None, binary=False):
        """Cached content for ``key``, or ``False`` on a cache miss."""
        path = self.has(key, ttl)
        if not path:
            return False
        try:
            with open(path, "rb") as handle:
                data = handle.read()
            mtime = os.stat(path).st_mtime
            os.utime(path, (time.time(), mtime))   # mark as recently used
        except OSError:
            return False
        if binary:
            return data
        return data.decode("utf-8", errors="surrogateescape")

    def export(self, key, target, ttl=None):
        """Copy the cached entry to ``target``; ``False`` on a cache miss."""
        path = self.has(key, ttl)
        if not path:
            return False
        try:
            directory = os.path.dirname(os.path.abspath(target))
            os.makedirs(directory, exist_ok=True)
            shutil.copyfile(path, target)
            mtime = os.stat(path).st_mtime
            os.utime(path, (time.time(), mtime))
        except OSError:
            return False
        return True

    # --- writing ----------------------------------------------------------

    def is_writable(self, key):
        if not self.enabled:
            return False
        path = self.filename(key)
        if os.path.exists(path):
            return os.path.isfile(path) and os.access(path, os.W_OK)
        directory = os.path.dirname(path)
        while not os.path.exists(directory):
            directory = os.path.dirname(directory)
        return os.path.isdir(directory) and os.access(directory, os.W_OK)

    def _prepare(self, key):
        if not self.enabled:
            return None
        path = self.filename(key)
        if not self._ensure_dir(os.path.dirname(path)):
            return None
        return path

    def _touch(self, path):
        now = time.time()
        os.utime(path, (now, now))

    def write(self, key, contents):
        """Store ``contents`` (text or bytes) under ``key``; return success."""
        path = self._prepare(key)
        if path is None:
            return False
        data = contents if isinstance(contents, bytes) else str(contents).encode(
            "utf-8", errors="surrogateescape")
        try:
            with open(path, "wb") as handle:
                handle.write(data)
            self._touch(path)
        except OSError:
            return False
        return True

    def import_file(self, key, source):
        """Store a copy of the file ``source`` under ``key``; return success."""
        path = self._prepare(key)
        if path is None or not os.path.isfile(source):
            return False
        try:
            shutil.copyfile(source, path)
            self._touch(path)
        except OSError:
            return False
        return True

    def remove(self, key):
        if not self.enabled:
            return False
        path = self.filename(key)
        return os.path.isfile(path) and self._unlink(path)

    # --- maintenance --------------------------------------------------------

    def clean(self, now=None):
        """Delete expired entries, then evict least recently used entries
        (ties broken by path) until the cache fits within ``max_size``."""
        if not self.enabled or not os.path.isdir(self.root):
            return False
        now = time.time() if now is None else now
        kept = []
        for path, size, mtime, recency in self._entries():
            if self._expired(mtime, self.ttl, now):
                self._unlink(path)
            else:
                kept.append((path, size, recency))
        if self.max_size > 0:
            total = 0
            for path, size, _ in sorted(kept, key=lambda e: (-e[2], e[0])):
                if total + size <= self.max_size:
                    total += size
                else:
                    self._unlink(path)
        self._prune_empty_dirs()
        return True

    def clear(self):
        """Delete every entry."""
        if not self.enabled or not os.path.isdir(self.root):
            return False
        for path, _, _, _ in self._entries():
            self._unlink(path)
        self._prune_empty_dirs()
        return True

    def size(self):
        return sum(size for _, size, _, _ in self._entries()) if self.enabled else 0
