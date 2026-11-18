#!/usr/bin/env python3
"""MTL command-line entry point."""
import sys

from mtl_engine.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
