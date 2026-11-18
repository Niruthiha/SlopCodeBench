"""Resumable run state.

Secret: the layout of the state directory (one state JSON per pipeline plus
content-addressed snapshots of the bytes each run consumed), validation and
compatibility rules for resuming, how a discovered file is classified as
unchanged (read back from its snapshot, never re-read from its source) or
new/modified (snapshotted, then processed from the snapshot), and the atomic
commit of a successful run.

Every file the pipeline consumes is read from its snapshot, so a resumed run
recomputes exactly the result of the files' committed contents: output is
byte-identical when nothing changed, and only new or modified files are read
from their original location.
"""

import hashlib
import json
import os
import re
import tempfile
from collections import OrderedDict, namedtuple

from . import fingerprints
from .errors import ArtifactError, InputError

DEFAULT_SOURCE = "default"
DEFAULT_PIPELINE = "default"
GRANULARITIES = ("file", "rowgroup", "line")
STATUS_DONE = "done"

FileUnit = namedtuple("FileUnit", "source path entry fingerprint skipped")
# path: canonical (real, absolute) path; entry: the inputs.InputFile as admitted;
# fingerprint: OrderedDict or None (not tracked); skipped: unchanged since the last run

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 1 << 20


class Checkpoints:
    """File admission and state bookkeeping for one run.

    Without a state directory files are admitted unchanged (fingerprints are
    computed only when `track` is set, for metadata).
    """

    def __init__(self, pipeline, scheme, identity, state_dir=None, resume=False,
                 granularity="file", track=False):
        self.pipeline = pipeline or DEFAULT_PIPELINE
        self.scheme = scheme
        self.identity = identity          # OrderedDict dsl_version, dsl_sha256, ingest_config_sha256
        self.state_dir = state_dir
        self.resume = resume
        self.granularity = granularity
        self.track = track or state_dir is not None
        self.units = []
        self._prior = {}                  # canonical path -> (fingerprint, status, snapshot)
        self._created_at = None
        if state_dir is None:
            return
        self.state_path = os.path.join(state_dir, "%s.state.json" % self.pipeline)
        self.snapshot_dir = os.path.join(state_dir, "%s.snapshots" % self.pipeline)
        if resume:
            self._load_prior()
        else:
            _ensure_dir(state_dir)

    # -- resuming -----------------------------------------------------------
    def _load_prior(self):
        if os.path.exists(self.state_dir) and not os.path.isdir(self.state_dir):
            raise ArtifactError("state-dir conflict: %r is not a directory" % self.state_dir)
        if not os.path.isfile(self.state_path):
            raise ArtifactError("cannot resume: no state for pipeline %r in %r"
                                % (self.pipeline, self.state_dir))
        try:
            with open(self.state_path, "rb") as handle:
                state = json.loads(handle.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise ArtifactError("cannot resume: malformed state file %r: %s"
                                % (self.state_path, exc))
        problem = _validate(state)
        if problem:
            raise ArtifactError("cannot resume: malformed state file %r: %s"
                                % (self.state_path, problem))
        if state["pipeline"] != self.pipeline:
            raise ArtifactError("state-dir conflict: %r holds state of pipeline %r, not %r"
                                % (self.state_path, state["pipeline"], self.pipeline))
        for key, what in (("dsl_sha256", "the DSL"), ("ingest_config_sha256", "the ingest config")):
            if state[key] != self.identity[key]:
                raise ArtifactError("cannot resume: breaking change, %s changed since the last "
                                    "run (%s mismatch); start a fresh run without --resume"
                                    % (what, key))
        snapshots = state.get("snapshots") or {}
        for item in state["last_run"]["files"]:
            self._prior[item["path"]] = (item["fingerprint"], item["status"],
                                         snapshots.get(item["path"]))
        self._created_at = state["created_at"]

    # -- admission ----------------------------------------------------------
    def admit(self, source, entry):
        """Register a discovered file of `source`; returns the InputFile to read."""
        canonical = os.path.realpath(entry.path)
        if self.state_dir is None:
            fingerprint = None
            if self.track:
                fingerprint = fingerprints.compute(self.scheme, entry.path, entry.gzipped)
            self.units.append(FileUnit(source, canonical, entry, fingerprint, False))
            return entry
        prior = self._prior.get(canonical)
        if prior is not None:
            fingerprint, status, digest = prior
            current = fingerprints.compute(self.scheme, entry.path, entry.gzipped)
            snapshot = self._snapshot_path(digest) if digest else None
            if (status == STATUS_DONE and current == fingerprint and snapshot is not None
                    and os.path.isfile(snapshot)):
                admitted = entry._replace(data_path=snapshot)
                self.units.append(FileUnit(source, canonical, admitted, current, True))
                return admitted
        snapshot, fingerprint = self._take_snapshot(entry)
        admitted = entry._replace(data_path=snapshot)
        self.units.append(FileUnit(source, canonical, admitted, fingerprint, False))
        return admitted

    def _snapshot_path(self, digest):
        if not isinstance(digest, str) or not _SHA256.match(digest):
            return None
        return os.path.join(self.snapshot_dir, digest)

    def _take_snapshot(self, entry):
        """Copy the file into the snapshot store; (snapshot path, fingerprint)."""
        _ensure_dir(self.snapshot_dir)
        try:
            source = open(entry.path, "rb")
        except OSError as exc:
            raise InputError("cannot read %r: %s" % (entry.path, exc.strerror or exc))
        with source:
            stat = os.fstat(source.fileno())
            try:
                fd, temp = tempfile.mkstemp(dir=self.snapshot_dir, prefix=".tmp-")
            except OSError as exc:
                raise ArtifactError("cannot write to state-dir %r: %s"
                                    % (self.state_dir, exc.strerror or exc))
            digest = hashlib.sha256()
            try:
                _default_mode(temp)
                with os.fdopen(fd, "wb") as target:
                    while True:
                        try:
                            chunk = source.read(_CHUNK)
                        except OSError as exc:
                            raise InputError("cannot read %r: %s"
                                             % (entry.path, exc.strerror or exc))
                        if not chunk:
                            break
                        digest.update(chunk)
                        target.write(chunk)
                final = os.path.join(self.snapshot_dir, digest.hexdigest())
                os.replace(temp, final)
            except OSError as exc:
                _discard(temp)
                raise ArtifactError("cannot write to state-dir %r: %s"
                                    % (self.state_dir, exc.strerror or exc))
            except BaseException:
                _discard(temp)
                raise
        if self.scheme == fingerprints.MTIME_SIZE:
            fingerprint = fingerprints.of_stat(stat)
        else:
            fingerprint = fingerprints.compute(self.scheme, final, entry.gzipped)
        return final, fingerprint

    # -- commit -------------------------------------------------------------
    def commit(self, run_id, started_at, completed_at, watermarks):
        """Atomically replace the state file to record this successful run."""
        if self.state_dir is None:
            return
        units = sorted(self.units, key=lambda u: u.path)
        files = [OrderedDict([("source", u.source), ("path", u.path),
                              ("fingerprint", u.fingerprint), ("status", STATUS_DONE)])
                 for u in units]
        marks = OrderedDict((name, OrderedDict([("max_timestamp_utc", watermarks[name])]))
                            for name in sorted(watermarks))
        snapshots = OrderedDict((u.path, os.path.basename(u.entry.data_path)) for u in units)
        state = OrderedDict([
            ("pipeline", self.pipeline),
            ("dsl_version", self.identity["dsl_version"]),
            ("dsl_sha256", self.identity["dsl_sha256"]),
            ("ingest_config_sha256", self.identity["ingest_config_sha256"]),
            ("created_at", self._created_at if self.resume else started_at),
            ("last_run", OrderedDict([
                ("run_id", run_id),
                ("completed_at", completed_at),
                ("files", files),
                ("watermarks", marks),
            ])),
            ("fingerprint_scheme", self.scheme),
            ("checkpoint_granularity", self.granularity),
            ("snapshots", snapshots),
        ])
        text = json.dumps(state, indent=2, ensure_ascii=False) + "\n"
        try:
            write_atomic(self.state_path, text.encode("utf-8"))
        except OSError as exc:
            raise ArtifactError("cannot write state file %r: %s"
                                % (self.state_path, exc.strerror or exc))
        self._collect_garbage(set(snapshots.values()))

    def _collect_garbage(self, keep):
        try:
            names = os.listdir(self.snapshot_dir)
        except OSError:
            return
        for name in names:
            if name not in keep:
                _discard(os.path.join(self.snapshot_dir, name))


def write_atomic(path, data):
    """Write bytes to `path` via a temporary file and a rename; raises OSError."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, temp = tempfile.mkstemp(dir=directory, prefix=".%s." % os.path.basename(path),
                                suffix=".tmp")
    try:
        _default_mode(temp)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        _discard(temp)
        raise


def _default_mode(path):
    """Give a mkstemp file the permissions an ordinary new file would get."""
    mask = os.umask(0)
    os.umask(mask)
    os.chmod(path, 0o666 & ~mask)


def _ensure_dir(path):
    if os.path.exists(path) and not os.path.isdir(path):
        raise ArtifactError("state-dir conflict: %r is not a directory" % path)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise ArtifactError("cannot create state-dir %r: %s" % (path, exc.strerror or exc))


def _discard(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _validate(state):
    """Why `state` is not a usable state document, or None."""
    if not isinstance(state, dict):
        return "not a JSON object"
    for key in ("pipeline", "dsl_version", "dsl_sha256", "created_at"):
        if not isinstance(state.get(key), str):
            return "missing or invalid %r" % key
    if "ingest_config_sha256" not in state or not isinstance(state["ingest_config_sha256"],
                                                             (str, type(None))):
        return "missing or invalid 'ingest_config_sha256'"
    run = state.get("last_run")
    if not isinstance(run, dict):
        return "missing or invalid 'last_run'"
    for key in ("run_id", "completed_at"):
        if not isinstance(run.get(key), str):
            return "missing or invalid 'last_run.%s'" % key
    files = run.get("files")
    if not isinstance(files, list):
        return "missing or invalid 'last_run.files'"
    for index, item in enumerate(files):
        if not (isinstance(item, dict) and isinstance(item.get("path"), str)
                and isinstance(item.get("source"), str) and isinstance(item.get("status"), str)
                and isinstance(item.get("fingerprint"), dict)
                and isinstance(item["fingerprint"].get("scheme"), str)):
            return "invalid entry last_run.files[%d]" % index
    if not isinstance(run.get("watermarks", {}), dict):
        return "invalid 'last_run.watermarks'"
    if not isinstance(state.get("snapshots", {}), dict):
        return "invalid 'snapshots'"
    return None
