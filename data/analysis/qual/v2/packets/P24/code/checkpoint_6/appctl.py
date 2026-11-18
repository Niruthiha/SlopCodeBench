#!/usr/bin/env python3
"""appctl: hierarchical command-line dispatcher."""

import os
import sys

from appctl_core.app import run


def main():
    return run(sys.argv[1:], os.environ, sys.stdout, sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
