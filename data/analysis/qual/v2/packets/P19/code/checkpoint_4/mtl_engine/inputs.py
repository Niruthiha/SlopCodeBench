"""Resolution of --input arguments (files, directories, globs) into an ordered file set."""
import glob
import os

from .errors import IOFailure

CSV = "csv"
TSV = "tsv"
PARQUET = "parquet"
AUTO = "auto"
FORMATS = (CSV, TSV, PARQUET, AUTO)

STDIN = "-"

_EXTENSIONS = (
    (".csv.gz", CSV), (".tsv.gz", TSV),
    (".csv", CSV), (".tsv", TSV), (".parquet", PARQUET),
)


class InputFile:
    """One file of the input set; `format` is None when it must be sniffed from content."""

    def __init__(self, path, file_format):
        self.path = path
        self.format = file_format


def format_from_name(name):
    """The format implied by a file name's extension (case-insensitive), or None."""
    lower = name.lower()
    for ext, fmt in _EXTENSIONS:
        if lower.endswith(ext):
            return fmt
    return None


def _has_extension(name):
    stem = name[:-3] if name.lower().endswith(".gz") else name
    return "." in stem.lstrip(".")


def resolve(patterns, recursive=False, forced=AUTO):
    """Return the union of files matched by all patterns, sorted by path.

    Explicit file paths are always used. Directory entries and glob matches
    are used when their extension is a supported one, or when they have no
    extension (their format is then forced by --format or sniffed).
    """
    forced = None if forced == AUTO else forced
    found = {}

    def add(path):
        display = os.path.normpath(path)
        key = os.path.realpath(path)
        if key not in found or display < found[key].path:
            fmt = format_from_name(os.path.basename(path)) or forced
            found[key] = InputFile(display, fmt)

    def add_candidate(path):
        name = os.path.basename(path)
        if name.startswith("."):
            return
        if format_from_name(name) is not None or not _has_extension(name):
            add(path)

    def add_directory(path):
        for entry in _scan(path, recursive):
            add_candidate(entry)

    stdin = None
    for pattern in patterns:
        if pattern == STDIN:
            stdin = InputFile(STDIN, forced or CSV)
        elif os.path.isdir(pattern):
            add_directory(pattern)
        elif os.path.exists(pattern):
            add(pattern)
        elif glob.has_magic(pattern):
            for match in sorted(glob.glob(pattern, recursive=recursive)):
                if os.path.isdir(match):
                    add_directory(match)
                elif os.path.isfile(match):
                    add_candidate(match)
        else:
            raise IOFailure(f"input '{pattern}' does not exist")

    files = sorted(found.values(), key=lambda f: f.path)
    if stdin is not None:
        files.insert(0, stdin)
    if not files:
        raise IOFailure("no input files matched: " + ", ".join(patterns))
    return files


def _scan(directory, recursive):
    try:
        if not recursive:
            names = sorted(os.listdir(directory))
            return [os.path.join(directory, n) for n in names
                    if os.path.isfile(os.path.join(directory, n))]
        result = []
        for root, dirs, names in os.walk(directory):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            result.extend(os.path.join(root, n) for n in sorted(names))
        return [p for p in result if os.path.isfile(p)]
    except OSError as exc:
        raise IOFailure(f"cannot list directory '{directory}': {exc}") from exc
