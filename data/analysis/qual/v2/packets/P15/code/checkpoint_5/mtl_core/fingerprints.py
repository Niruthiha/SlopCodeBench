"""File fingerprints.

Secret: how an input file is identified across runs -- the mtime/size
scheme and the content-hash scheme (XXH64 of the decompressed bytes for
gzip files), and the fallback hash implementation when the xxhash package
is unavailable.
"""

import gzip
import os
import struct
import zlib
from collections import OrderedDict

from .errors import InputError

MTIME_SIZE = "mtime_size"
XXHASH64 = "xxhash64"
SCHEMES = (MTIME_SIZE, XXHASH64)

_CHUNK = 1 << 20


def of_stat(st):
    """The mtime_size fingerprint of an os.stat_result."""
    return OrderedDict([("scheme", MTIME_SIZE),
                        ("mtime_epoch_ms", st.st_mtime_ns // 1000000),
                        ("size_bytes", st.st_size)])


def compute(scheme, path, gzipped):
    """Fingerprint of the file at `path` under `scheme`."""
    if scheme == MTIME_SIZE:
        try:
            return of_stat(os.stat(path))
        except OSError as exc:
            raise InputError("cannot read %r: %s" % (path, exc.strerror or exc))
    return OrderedDict([("scheme", XXHASH64), ("hash", _content_hash(path, gzipped))])


def _content_hash(path, gzipped):
    try:
        with open(path, "rb") as handle:
            magic = handle.read(2)
    except OSError as exc:
        raise InputError("cannot read %r: %s" % (path, exc.strerror or exc))
    if gzipped or magic == b"\x1f\x8b":
        try:
            with gzip.open(path, "rb") as handle:
                return _hash_stream(handle)
        except (OSError, EOFError, zlib.error):
            pass  # not really gzip: hash the raw bytes; reading reports the problem
    try:
        with open(path, "rb") as handle:
            return _hash_stream(handle)
    except OSError as exc:
        raise InputError("cannot read %r: %s" % (path, exc.strerror or exc))


def _hash_stream(handle):
    try:
        import xxhash
    except ImportError:
        return "%016x" % xxh64(handle.read())
    state = xxhash.xxh64(seed=0)
    while True:
        chunk = handle.read(_CHUNK)
        if not chunk:
            return state.hexdigest()
        state.update(chunk)


# ---------------------------------------------------------------------------
# XXH64 (seed 0 by default), used when the xxhash package is not installed.

_M = (1 << 64) - 1
_P1 = 11400714785074694791
_P2 = 14029467366897019727
_P3 = 1609587929392839161
_P4 = 9650029242287828579
_P5 = 2870177450012600261


def _rotl(x, r):
    return ((x << r) | (x >> (64 - r))) & _M


def _round(acc, lane):
    acc = (acc + lane * _P2) & _M
    return (_rotl(acc, 31) * _P1) & _M


def _merge(acc, value):
    acc ^= _round(0, value)
    return (acc * _P1 + _P4) & _M


def xxh64(data, seed=0):
    n = len(data)
    i = 0
    if n >= 32:
        v1 = (seed + _P1 + _P2) & _M
        v2 = (seed + _P2) & _M
        v3 = seed & _M
        v4 = (seed - _P1) & _M
        while i <= n - 32:
            a, b, c, d = struct.unpack_from("<4Q", data, i)
            v1, v2, v3, v4 = _round(v1, a), _round(v2, b), _round(v3, c), _round(v4, d)
            i += 32
        h = (_rotl(v1, 1) + _rotl(v2, 7) + _rotl(v3, 12) + _rotl(v4, 18)) & _M
        for v in (v1, v2, v3, v4):
            h = _merge(h, v)
    else:
        h = (seed + _P5) & _M
    h = (h + n) & _M
    while i + 8 <= n:
        (lane,) = struct.unpack_from("<Q", data, i)
        h ^= _round(0, lane)
        h = (_rotl(h, 27) * _P1 + _P4) & _M
        i += 8
    if i + 4 <= n:
        (lane,) = struct.unpack_from("<I", data, i)
        h ^= (lane * _P1) & _M
        h = (_rotl(h, 23) * _P2 + _P3) & _M
        i += 4
    while i < n:
        h ^= (data[i] * _P5) & _M
        h = (_rotl(h, 11) * _P1) & _M
        i += 1
    h ^= h >> 33
    h = (h * _P2) & _M
    h ^= h >> 29
    h = (h * _P3) & _M
    h ^= h >> 32
    return h
