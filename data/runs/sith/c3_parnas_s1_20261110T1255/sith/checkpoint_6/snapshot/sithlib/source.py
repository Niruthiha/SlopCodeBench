"""Source file access.

Secret: how a file on disk is read, decoded and split into lines, and how a
(1-based line, 0-based column) cursor is validated against it.
"""

import os


class SourceError(Exception):
    """The file cannot be used as input (missing, undecodable, bad cursor)."""


class SourceFile:
    def __init__(self, path):
        if not os.path.isfile(path):
            raise SourceError("not a regular file: %s" % path)
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except OSError as exc:
            raise SourceError("cannot read %s: %s" % (path, exc))
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise SourceError("file is not valid UTF-8: %s" % path)
        if text.startswith("\ufeff"):
            text = text[1:]
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        self._path = os.path.abspath(path)
        self._lines = text.split("\n")

    @property
    def path(self):
        return self._path

    def text(self):
        return "\n".join(self._lines)

    def lines(self):
        """The file's lines without line terminators (a copy)."""
        return list(self._lines)

    def check_position(self, line, col):
        if line < 1 or line > len(self._lines):
            raise SourceError("line %d out of range" % line)
        if col < 0 or col > len(self._lines[line - 1]):
            raise SourceError("column %d out of range" % col)

    def text_before(self, line, col):
        """All text from the start of the file up to the cursor."""
        head = self._lines[: line - 1]
        head.append(self._lines[line - 1][:col])
        return "\n".join(head)
