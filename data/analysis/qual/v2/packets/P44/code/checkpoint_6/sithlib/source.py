"""Loading source documents and validating cursor positions."""
import os
from dataclasses import dataclass, field

from .errors import SithError


@dataclass
class Document:
    """A source file split into lines, with cursor-related helpers."""

    path: str
    text: str
    lines: list = field(default_factory=list)

    @property
    def directory(self):
        return os.path.dirname(os.path.abspath(self.path))

    def check_position(self, line, col):
        """Validate a 1-based line and 0-based column."""
        if line < 1 or line > len(self.lines):
            raise SithError(f"line {line} is out of range (file has {len(self.lines)} lines)")
        length = len(self.lines[line - 1])
        if col < 0 or col > length:
            raise SithError(f"column {col} is out of range (line {line} has {length} characters)")

    def text_before(self, line, col):
        """All source text preceding the cursor."""
        return "\n".join(self.lines[: line - 1] + [self.lines[line - 1][:col]])


def normalize_newlines(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_text(path):
    """Read a file as UTF-8 text, raising SithError on any problem."""
    if not os.path.exists(path):
        raise SithError(f"file not found: {path}")
    if not os.path.isfile(path):
        raise SithError(f"not a regular file: {path}")
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise SithError(f"cannot read {path}: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SithError(f"file is not valid UTF-8: {path}") from exc
    if text.startswith("\ufeff"):
        text = text[1:]
    return normalize_newlines(text)


def load_document(path):
    text = read_text(path)
    return Document(path=path, text=text, lines=text.split("\n"))
