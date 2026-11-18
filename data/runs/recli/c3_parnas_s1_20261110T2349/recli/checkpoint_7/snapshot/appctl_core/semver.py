"""Semantic version parsing and precedence (SemVer 2.0.0).

Secret: which textual forms are accepted (an optional ``v`` prefix, missing
minor/patch parts, surrounding text) and how pre-release identifiers are
ordered.
"""

import re
from functools import total_ordering

_PATTERN = re.compile(
    r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?")


@total_ordering
class Version:
    def __init__(self, major, minor=0, patch=0, prerelease=(), build=()):
        self.major = int(major)
        self.minor = int(minor)
        self.patch = int(patch)
        self.prerelease = tuple(prerelease)
        self.build = tuple(build)

    def _key(self):
        # A version without pre-release identifiers has higher precedence.
        pre = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in self.prerelease)
        return (self.major, self.minor, self.patch, not self.prerelease, pre)

    def __eq__(self, other):
        return isinstance(other, Version) and self._key() == other._key()

    def __lt__(self, other):
        return self._key() < other._key()

    def __hash__(self):
        return hash(self._key())

    def __str__(self):
        text = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            text += "-" + ".".join(self.prerelease)
        if self.build:
            text += "+" + ".".join(self.build)
        return text

    def __repr__(self):
        return f"Version('{self}')"


def parse(text):
    """The first version found in ``text``, or ``None``."""
    if isinstance(text, Version):
        return text
    match = _PATTERN.search(str(text or ""))
    if match is None:
        return None
    major, minor, patch, pre, build = match.groups()
    return Version(major, minor or 0, patch or 0,
                   pre.split(".") if pre else (), build.split(".") if build else ())


def compare(a, b):
    """-1, 0 or 1 as version ``a`` is lower than, equal to or higher than ``b``."""
    va, vb = parse(a), parse(b)
    if va is None or vb is None:
        raise ValueError(f"Invalid version: {a if va is None else b}")
    return (va > vb) - (va < vb)


def is_lower(a, b):
    return compare(a, b) < 0
