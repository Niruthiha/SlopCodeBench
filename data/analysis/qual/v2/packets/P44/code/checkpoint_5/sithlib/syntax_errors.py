"""The `errors` command: the syntax errors of a file.

The first error is the one the parser reports. Further errors are found by
repairing the offending lines the way the tolerant parser does and parsing
again; errors reported on lines that were already repaired are artifacts of
the repair and are left out.
"""
import warnings
from dataclasses import asdict, dataclass

from .parsing import _Repairer
from .source import read_text


@dataclass
class SyntaxErrorReport:
    line: int
    column: int
    until_line: int
    until_column: int
    message: str

    def to_dict(self):
        return asdict(self)


def syntax_errors(path):
    text = read_text(path)
    lines = text.replace("\0", " ").split("\n")
    collector = _Collector(lines, text.split("\n"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        collector.run()
    if "\0" in text and not collector.errors:
        line = text[:text.index("\0")].count("\n") + 1
        column = len(text[:text.index("\0")].split("\n")[-1])
        collector.errors.append(SyntaxErrorReport(
            line, column, line, column + 1, "source code cannot contain null bytes"))
    return sorted(collector.errors, key=lambda e: (e.line, e.column))


class _Collector(_Repairer):
    def __init__(self, lines, original_lines):
        super().__init__(lines, None)
        self.original_lines = original_lines
        self.errors = []
        self.touched = set()

    def _repair(self, error):
        self._record(error)
        before = list(self.state)
        repaired = super()._repair(error)
        self.touched.update(index + 1 for index, (old, new) in enumerate(zip(before, self.state))
                            if old != new)
        return repaired

    def _record(self, error):
        lines = self.original_lines
        count = len(lines)
        line = getattr(error, "lineno", None) or count
        offset = getattr(error, "offset", None) or 1
        if line > count:
            line = count
            offset = len(lines[-1]) + 1
        line = max(1, line)
        if line in self.touched or any(e.line == line for e in self.errors):
            return
        if self.touched and line - 1 in self.touched and \
                "expected an indented block" in str(getattr(error, "msg", "")):
            return
        length = len(lines[line - 1])
        column = max(0, min(offset - 1, length))
        until_line = getattr(error, "end_lineno", None) or line
        end_offset = getattr(error, "end_offset", None)
        if until_line < line or until_line > count:
            until_line = line
        if end_offset is None or end_offset <= 0:
            until_column = column
        else:
            until_column = min(end_offset - 1, len(lines[until_line - 1]))
        if (until_line, until_column) <= (line, column):
            until_line, until_column = line, min(column + 1, length) if length > column else column
        message = str(getattr(error, "msg", None) or error)
        self.errors.append(SyntaxErrorReport(line, column, until_line, until_column, message))
