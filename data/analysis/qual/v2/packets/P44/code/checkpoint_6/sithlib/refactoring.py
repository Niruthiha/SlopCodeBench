"""Shared machinery of the refactoring commands: edits, validation and output.

A refactoring never touches the disk: it computes the new contents of the
files it changes (and the paths it renames) and reports them, either as JSON
or as a unified diff.
"""
import ast
import copy
import difflib
import keyword
import os
import warnings

from .definitions import posix_path
from .errors import SithError
from .source import load_document


class Refactoring:
    """The outcome of a refactoring: new file contents and renamed paths."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.old_texts = {}  # absolute path -> original text
        self.new_texts = {}  # absolute path -> new text
        self.renames = []  # (old absolute path, new absolute path)

    def change(self, path, old_text, new_text):
        path = os.path.abspath(path)
        self.old_texts.setdefault(path, old_text)
        self.new_texts[path] = new_text

    def rename(self, old_path, new_path):
        self.renames.append((os.path.abspath(old_path), os.path.abspath(new_path)))

    def relative(self, path):
        relative = os.path.relpath(path, self.root)
        if relative == os.pardir or relative.startswith(os.pardir + os.sep):
            return posix_path(path)
        return posix_path(relative)

    def moved(self, path):
        """Where the file at `path` ends up once the renames are applied."""
        for old, new in self.renames:
            if path == old:
                return new
            if path.startswith(old + os.sep):
                return new + path[len(old):]
        return path

    def changed(self):
        """(old path, new path, old text, new text) of every file whose content changed."""
        for path in sorted(self.new_texts):
            old_text, new_text = self.old_texts[path], self.new_texts[path]
            if old_text != new_text:
                yield path, self.moved(path), old_text, new_text

    def to_dict(self):
        return {
            "changed_files": {self.relative(new): text for _, new, _, text in self.changed()},
            "renames": {self.relative(old): self.relative(new) for old, new in self.renames},
        }

    def to_diff(self):
        parts = []
        for old, new in self.renames:
            parts.append(f"rename from {self.relative(old)}\nrename to {self.relative(new)}\n")
        for old_path, new_path, old_text, new_text in self.changed():
            old_lines = _diff_lines(old_text)
            new_lines = _diff_lines(new_text)
            parts.append("".join(difflib.unified_diff(
                old_lines, new_lines, fromfile=self.relative(old_path),
                tofile=self.relative(new_path))))
        return "".join(parts)


def _diff_lines(text):
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n\\ No newline at end of file\n"
    return lines


# -- validation ----------------------------------------------------------------------

def check_identifier(name, option="--new-name"):
    if not name.isidentifier() or keyword.iskeyword(name):
        raise SithError(f"{option} {name!r} is not a valid Python identifier")


def parse_strict(text, path):
    """The syntax tree of `text`; refactoring a file with syntax errors is refused."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return ast.parse(text)
    except (SyntaxError, ValueError) as error:
        raise SithError(f"cannot refactor {path}: it has syntax errors ({error})") from error


class Source:
    """A file being refactored: its text, lines, strict syntax tree and parent links."""

    def __init__(self, path):
        document = load_document(path)
        self.path = os.path.abspath(path)
        self.text = document.text
        self.lines = document.lines
        self.document = document
        self.tree = parse_strict(self.text, path)
        self.parents = {}
        for parent in ast.walk(self.tree):
            for child in ast.iter_child_nodes(parent):
                self.parents[id(child)] = parent
        offsets = [0]
        for line in self.lines:
            offsets.append(offsets[-1] + len(line) + 1)
        self._offsets = offsets

    # positions: (1-based line, 0-based character column) <-> absolute offsets

    def offset(self, line, col):
        return self._offsets[line - 1] + col

    def position(self, offset):
        line = 1
        while line < len(self._offsets) - 1 and self._offsets[line] <= offset:
            line += 1
        return line, offset - self._offsets[line - 1]

    def char_col(self, line, byte_col):
        encoded = self.lines[line - 1].encode("utf-8")
        return len(encoded[:byte_col].decode("utf-8", errors="ignore"))

    def start(self, node):
        """Absolute offset of the start of `node`."""
        return self.offset(node.lineno, self.char_col(node.lineno, node.col_offset))

    def end(self, node):
        return self.offset(node.end_lineno, self.char_col(node.end_lineno, node.end_col_offset))

    def segment(self, node):
        return self.text[self.start(node):self.end(node)]

    def parent(self, node):
        return self.parents.get(id(node))

    def indent_of(self, line):
        text = self.lines[line - 1]
        return text[:len(text) - len(text.lstrip())]


def apply_edits(text, edits):
    """Apply non-overlapping (start, end, replacement) edits to `text`."""
    for start, end, replacement in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


# -- comparing syntax trees ----------------------------------------------------------

def dump(tree):
    return ast.dump(tree, include_attributes=False)


def replaced_tree(tree, targets):
    """A copy of `tree` with nodes replaced: `targets` maps id(old node) -> new node."""
    nodes = list(ast.walk(tree))
    indexes = {id(node): index for index, node in enumerate(nodes)}
    duplicate = copy.deepcopy(tree)
    copies = list(ast.walk(duplicate))
    replacements = {id(copies[indexes[old]]): new for old, new in targets.items()}
    for parent in copies:
        for field, value in ast.iter_fields(parent):
            if isinstance(value, list):
                for index, item in enumerate(value):
                    if id(item) in replacements:
                        value[index] = copy.deepcopy(replacements[id(item)])
            elif id(value) in replacements:
                setattr(parent, field, copy.deepcopy(replacements[id(value)]))
    return duplicate


def same_tree(text, expected_dump):
    """True when `text` parses to the tree dumped as `expected_dump`."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return dump(ast.parse(text)) == expected_dump
    except (SyntaxError, ValueError):
        return False
