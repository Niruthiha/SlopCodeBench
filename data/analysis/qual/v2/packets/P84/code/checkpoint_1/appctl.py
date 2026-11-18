#!/usr/bin/env python3
"""appctl - hierarchical command-line tool entry point."""

import sys

from appctl_cli.app import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
