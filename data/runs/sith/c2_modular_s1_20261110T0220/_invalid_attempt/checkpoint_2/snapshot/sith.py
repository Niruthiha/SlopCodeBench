#!/usr/bin/env python3
"""sith - a static Python code intelligence tool.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy]
"""
import sys

from sithlib.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
