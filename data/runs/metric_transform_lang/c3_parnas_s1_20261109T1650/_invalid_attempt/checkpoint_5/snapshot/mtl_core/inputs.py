"""Input discovery.

Secret: how --input arguments (files, directories, globs) expand to the
effective set of files, which files a directory walk picks up, how the
format of each file is decided from its name, and the canonical order in
which files are processed.
"""

import glob
import os
from collections import namedtuple

from .errors import InputError

CSV = "csv"
TSV = "tsv"
PARQUET = "parquet"
AUTO = "auto"
FORMATS = (CSV, TSV, PARQUET, AUTO)

InputFile = namedtuple("InputFile", "path format gzipped")

_SUFFIXES = (
    (".csv.gz", CSV, True),
    (".tsv.gz", TSV, True),
    (".csv", CSV, False),
    (".tsv", TSV, False),
    (".parquet", PARQUET, False),
)


def detect(name, forced):
    """(format, gzipped) for a file name, or None if it cannot be decided."""
    lowered = name.lower()
    for suffix, fmt, gz in _SUFFIXES:
        if lowered.endswith(suffix):
            return fmt, gz
    if forced in (CSV, TSV, PARQUET):
        return forced, lowered.endswith(".gz")
    return None


def _hidden(name):
    return name.startswith(".")


def _walk(directory, recursive):
    found = []
    if recursive:
        for root, dirs, files in os.walk(directory):
            dirs[:] = sorted(d for d in dirs if not _hidden(d))
            found.extend(os.path.join(root, f) for f in files if not _hidden(f))
    else:
        try:
            names = os.listdir(directory)
        except OSError as exc:
            raise InputError("cannot list directory %r: %s" % (directory, exc.strerror or exc))
        found.extend(os.path.join(directory, n) for n in names if not _hidden(n))
    return [p for p in found if os.path.isfile(p)]


def expand(spec, forced=AUTO, recursive=False):
    """Files named by one path-or-glob, as a dict realpath -> InputFile.

    An explicitly named file must have a recognisable format and a path
    that is neither a file, a directory nor a glob is an error; files
    reached through a directory or a glob are skipped when their format
    cannot be decided.
    """
    chosen = {}

    def add(path, explicit):
        name = os.path.basename(path)
        if not explicit and name.startswith("_") and detect(name, AUTO) is None:
            return  # marker files such as _SUCCESS
        detected = detect(name, forced)
        if detected is None:
            if explicit:
                raise InputError("cannot determine the format of %r (use --format)" % path)
            return
        display = os.path.normpath(path)
        key = os.path.realpath(path)
        current = chosen.get(key)
        if current is None or display < current.path:
            chosen[key] = InputFile(display, detected[0], detected[1])

    if os.path.isdir(spec):
        for path in _walk(spec, recursive):
            add(path, False)
    elif os.path.isfile(spec):
        add(spec, True)
    elif glob.has_magic(spec):
        for match in sorted(glob.glob(spec, recursive=True)):
            if os.path.isdir(match):
                for path in _walk(match, recursive):
                    add(path, False)
            elif os.path.isfile(match):
                add(match, False)
    else:
        raise InputError("input %r does not exist" % spec)
    return chosen


def resolve(specs, recursive=False, forced=AUTO):
    """Expand (path-or-glob, forced_format) pairs into a sorted list of InputFile."""
    chosen = {}
    for spec, override in specs:
        for key, entry in expand(spec, override or forced, recursive).items():
            current = chosen.get(key)
            if current is None or entry.path < current.path:
                chosen[key] = entry
    if not chosen:
        raise InputError("no input files found")
    return sorted(chosen.values(), key=lambda f: f.path)
