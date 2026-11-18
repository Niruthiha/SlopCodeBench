"""sith - static Python code completion.

Usage: python sith.py complete <file> <line> <col> [--fuzzy]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sithlib import engine, output  # noqa: E402
from sithlib.source import SourceError  # noqa: E402

USAGE = "usage: sith.py complete <file> <line> <col> [--fuzzy]"


def _fail(message):
    sys.stderr.write("error: %s\n" % message)
    return 1


def main(argv):
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
    fuzzy = "--fuzzy" in argv
    args = [a for a in argv if a != "--fuzzy"]
    if len(args) != 4 or args[0] != "complete":
        return _fail(USAGE)
    try:
        line, col = int(args[2]), int(args[3])
    except ValueError:
        return _fail("line and column must be integers")
    try:
        completions = engine.complete(args[1], line, col, fuzzy)
    except SourceError as exc:
        return _fail(str(exc))
    except Exception:  # analysis must never crash on odd input; degrade to nothing
        completions = []
    output.write_completions(completions)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
