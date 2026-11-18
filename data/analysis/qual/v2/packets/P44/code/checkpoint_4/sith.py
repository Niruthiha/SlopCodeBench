#!/usr/bin/env python3
"""sith - a static Python code intelligence tool.

Usage:
    python sith.py complete <file> <line> <col> [--fuzzy] [--project DIR]
    python sith.py infer <file> <line> <col> [--project DIR]
    python sith.py goto <file> <line> <col> [--follow-imports] [--project DIR]
    python sith.py signatures <file> <line> <col> [--project DIR]
    python sith.py references <file> <line> <col> [--scope file|project] [--project DIR]
    python sith.py search <query> [--project DIR]
    python sith.py names <file> [--all-scopes] [--project DIR]
"""
import sys

from sithlib.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
