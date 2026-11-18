"""Resumable runs: input fingerprints, per-file checkpoints and the persistent state file.

With --state-dir every input file that is read is checkpointed: its parsed content
is stored under `<state-dir>/<pipeline>.checkpoints/`, keyed by its canonical path,
format and fingerprint. A resumed run reuses the checkpoint of every file whose
fingerprint matches a `done` entry of the previous state instead of reading the
file again, then replays evaluation over all files, so its output is identical to
that of a run over the same inputs. The state file is replaced atomically, and
only after the run succeeded.
"""
import gzip
import hashlib
import json
import os
import pickle
import re
import tempfile
import uuid
import zlib
from datetime import datetime, timezone

from . import inputs, loader
from .errors import ArtifactError, IOFailure
from .timeutil import format_utc

MTIME_SIZE = "mtime_size"
XXHASH64 = "xxhash64"
SCHEMES = (MTIME_SIZE, XXHASH64)
GRANULARITIES = ("file", "rowgroup", "line")
DEFAULT_SOURCE = "default"
DONE = "done"

_CHUNK = 1 << 20
_GZIP_MAGIC = b"\x1f\x8b"


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def now_utc():
    return datetime.now(timezone.utc)


def iso_z(dt):
    """ISO 8601 UTC with millisecond precision and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# --------------------------------------------------------------------------- fingerprints


def fingerprint(path, scheme):
    try:
        if scheme == MTIME_SIZE:
            st = os.stat(path)
            return {"scheme": MTIME_SIZE, "mtime_epoch_ms": st.st_mtime_ns // 1_000_000,
                    "size_bytes": st.st_size}
        return {"scheme": XXHASH64, "hash": _content_hash(path)}
    except OSError as exc:
        raise IOFailure(f"cannot read '{path}': {exc}") from exc


def _content_hash(path):
    """xxHash64 of the file's content; gzip files are hashed decompressed."""
    with open(path, "rb") as fh:
        gzipped = fh.read(2) == _GZIP_MAGIC
    if gzipped:
        try:
            with gzip.open(path, "rb") as fh:
                return _hash_stream(fh)
        except (OSError, EOFError, zlib.error):
            pass  # not really gzip: hash the raw bytes; reading it will report the problem
    with open(path, "rb") as fh:
        return _hash_stream(fh)


def _hash_stream(fh):
    try:
        import xxhash
    except ImportError:  # pragma: no cover - dependency is in requirements.txt
        return f"{_xxh64(fh.read()):016x}"
    hasher = xxhash.xxh64()
    for chunk in iter(lambda: fh.read(_CHUNK), b""):
        hasher.update(chunk)
    return hasher.hexdigest()


_P1, _P2, _P3 = 11400714785074694791, 14029467366897019727, 1609587929392839161
_P4, _P5 = 9650029242287828579, 2870177450012600261
_M = (1 << 64) - 1


def _rotl(x, r):
    return ((x << r) | (x >> (64 - r))) & _M


def _round(acc, value):
    return (_rotl((acc + value * _P2) & _M, 31) * _P1) & _M


def _xxh64(data, seed=0):
    """Pure-Python XXH64, used when the xxhash package is unavailable."""
    n = len(data)
    i = 0
    if n >= 32:
        v = [(seed + _P1 + _P2) & _M, (seed + _P2) & _M, seed, (seed - _P1) & _M]
        while i + 32 <= n:
            for lane in range(4):
                v[lane] = _round(v[lane], int.from_bytes(data[i:i + 8], "little"))
                i += 8
        h = (_rotl(v[0], 1) + _rotl(v[1], 7) + _rotl(v[2], 12) + _rotl(v[3], 18)) & _M
        for lane in v:
            h = ((h ^ _round(0, lane)) * _P1 + _P4) & _M
    else:
        h = (seed + _P5) & _M
    h = (h + n) & _M
    while i + 8 <= n:
        h ^= _round(0, int.from_bytes(data[i:i + 8], "little"))
        h = (_rotl(h, 27) * _P1 + _P4) & _M
        i += 8
    if i + 4 <= n:
        h ^= (int.from_bytes(data[i:i + 4], "little") * _P1) & _M
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
    return h ^ (h >> 32)


# --------------------------------------------------------------------------- run state


class FileRecord:
    """One input file of this run (STDIN has no canonical path or fingerprint)."""

    def __init__(self, source, path, display, fingerprint_, file_format, rows_read, key):
        self.source = source
        self.path = path
        self.display = display
        self.fingerprint = fingerprint_
        self.format = file_format
        self.rows_read = rows_read
        self.key = key


class RunState:
    def __init__(self, pipeline, dsl_version, dsl_sha256, config_sha256, scheme=MTIME_SIZE,
                 state_dir=None, resume=False):
        self.run_id = str(uuid.uuid4())
        self.started_at = now_utc()
        self.pipeline = pipeline
        self.dsl_version = dsl_version
        self.dsl_sha256 = dsl_sha256
        self.config_sha256 = config_sha256
        self.scheme = scheme
        self.state_dir = state_dir
        self.resume = resume
        self.files = []
        self.watermarks = {}
        self.created_at = None
        self.previous = {}
        if resume and state_dir is None:
            raise ArtifactError("--resume requires --state-dir")
        if state_dir is None:
            return
        stem = _safe_name(pipeline)
        self.state_path = os.path.join(state_dir, stem + ".state.json")
        self.checkpoint_dir = os.path.join(state_dir, stem + ".checkpoints")
        if os.path.exists(state_dir) and not os.path.isdir(state_dir):
            raise ArtifactError(f"state dir '{state_dir}' exists and is not a directory")
        if resume:
            self._load_previous()
        else:
            _makedirs(state_dir)

    # -- previous state --------------------------------------------------
    def _load_previous(self):
        path = self.state_path
        if not os.path.isfile(path):
            raise ArtifactError(f"cannot resume: no state file '{path}'")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise ArtifactError(f"cannot resume: malformed state file '{path}': {exc}") from exc
        files = _validate(data, path)
        if data["pipeline"] != self.pipeline:
            raise ArtifactError(f"cannot resume: state file '{path}' belongs to pipeline "
                                f"'{data['pipeline']}', not '{self.pipeline}'")
        if data["dsl_sha256"] != self.dsl_sha256:
            raise ArtifactError("cannot resume: breaking change: the DSL changed since the "
                                "last run (dsl_sha256 mismatch)")
        if data["ingest_config_sha256"] != self.config_sha256:
            raise ArtifactError("cannot resume: breaking change: the ingest config changed "
                                "since the last run (ingest_config_sha256 mismatch)")
        self.created_at = data.get("created_at")
        self.previous = {entry["path"]: entry for entry in files}

    # -- inputs -------------------------------------------------------------
    def open(self, source, input_file):
        """Open one input file, from its checkpoint when the previous run completed it."""
        if input_file.path == inputs.STDIN:
            opened = loader.open_source(input_file)
            self.files.append(FileRecord(source, inputs.STDIN, inputs.STDIN, None,
                                         opened.format, opened.rows_read, None))
            return opened
        canonical = os.path.realpath(input_file.path)
        fp = fingerprint(canonical, self.scheme)
        key = sha256_hex(json.dumps([canonical, input_file.format, fp],
                                    sort_keys=True).encode("utf-8"))
        opened = None
        prev = self.previous.get(canonical)
        if prev is not None and prev.get("status") == DONE and prev.get("fingerprint") == fp:
            opened = self._read_checkpoint(key)
        if opened is None:
            opened = loader.open_source(input_file)
            if self.state_dir is not None:
                self._write_checkpoint(key, opened)
        else:
            opened.path = input_file.path
        self.files.append(FileRecord(source, canonical, input_file.path, fp, opened.format,
                                     opened.rows_read, key))
        return opened

    def observe_timestamps(self, source, values):
        """Track the maximum event timestamp seen per source (advisory watermark)."""
        best = self.watermarks.get(source)
        for value in values:
            if isinstance(value, datetime) and (best is None or value > best):
                best = value
        self.watermarks[source] = best

    def _checkpoint_path(self, key):
        return os.path.join(self.checkpoint_dir, key + ".pkl")

    def _read_checkpoint(self, key):
        try:
            with open(self._checkpoint_path(key), "rb") as fh:
                return pickle.load(fh)
        except Exception:  # missing or unreadable checkpoint: process the file again
            return None

    def _write_checkpoint(self, key, opened):
        _makedirs(self.checkpoint_dir)
        _atomic_write(self._checkpoint_path(key),
                      pickle.dumps(opened, protocol=pickle.HIGHEST_PROTOCOL))

    # -- commit -------------------------------------------------------------
    def finish(self):
        self.completed_at = now_utc()

    def commit(self):
        """Atomically replace the state file, then drop unreferenced checkpoints."""
        if self.state_dir is None:
            return
        tracked = sorted((f for f in self.files if f.key is not None), key=lambda f: f.path)
        state = {
            "pipeline": self.pipeline,
            "dsl_version": self.dsl_version,
            "dsl_sha256": self.dsl_sha256,
            "ingest_config_sha256": self.config_sha256,
            "created_at": self.created_at or iso_z(self.completed_at),
            "last_run": {
                "run_id": self.run_id,
                "completed_at": iso_z(self.completed_at),
                "files": [{"source": f.source, "path": f.path, "fingerprint": f.fingerprint,
                           "status": DONE} for f in tracked],
                "watermarks": {name: {"max_timestamp_utc": None if ts is None else format_utc(ts)}
                               for name, ts in sorted(self.watermarks.items())},
            },
        }
        text = json.dumps(state, indent=2, ensure_ascii=False) + "\n"
        _makedirs(self.state_dir)
        _atomic_write(self.state_path, text.encode("utf-8"))
        keep = {f.key + ".pkl" for f in tracked}
        try:
            names = os.listdir(self.checkpoint_dir)
        except OSError:
            return
        for name in names:
            if name not in keep:
                try:
                    os.remove(os.path.join(self.checkpoint_dir, name))
                except OSError:
                    pass


def _validate(data, path):
    def bad(why):
        raise ArtifactError(f"cannot resume: malformed state file '{path}': {why}")

    if not isinstance(data, dict):
        bad("not a JSON object")
    for key in ("pipeline", "dsl_sha256"):
        if not isinstance(data.get(key), str):
            bad(f"'{key}' must be a string")
    if "ingest_config_sha256" not in data or not (
            data["ingest_config_sha256"] is None or isinstance(data["ingest_config_sha256"], str)):
        bad("'ingest_config_sha256' must be a string or null")
    last = data.get("last_run")
    if not isinstance(last, dict):
        bad("'last_run' must be an object")
    files = last.get("files")
    if not isinstance(files, list):
        bad("'last_run.files' must be a list")
    for entry in files:
        if not (isinstance(entry, dict) and isinstance(entry.get("path"), str)
                and isinstance(entry.get("fingerprint"), dict)
                and isinstance(entry.get("status"), str)):
            bad("every 'last_run.files' entry needs path, fingerprint and status")
    return files


def _safe_name(name):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name) or DEFAULT_SOURCE


def _makedirs(path):
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise ArtifactError(f"cannot create state dir '{path}': {exc}") from exc


def _atomic_write(path, data):
    """Write to a temporary file in the target's directory, then rename over the target."""
    directory = os.path.dirname(os.path.abspath(path))
    try:
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    except OSError as exc:
        raise ArtifactError(f"cannot write state '{path}': {exc}") from exc
