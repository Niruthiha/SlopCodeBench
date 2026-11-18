#!/usr/bin/env python3
"""Build the appctl distribution archive (a self-contained zipapp).

Usage: build_archive.py [<output>]   (default: dist/appctl.pyz)
"""

import os
import shutil
import sys
import tempfile
import zipapp

ROOT = os.path.dirname(os.path.abspath(__file__))
_MAIN = """import os
import sys

from appctl_core.app import run

sys.exit(run(sys.argv[1:], os.environ, sys.stdout, sys.stderr))
"""


def build(output, source=ROOT, interpreter="/usr/bin/env python3"):
    staging = tempfile.mkdtemp(prefix="appctl-build-")
    try:
        shutil.copytree(os.path.join(source, "appctl_core"),
                        os.path.join(staging, "appctl_core"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        with open(os.path.join(staging, "__main__.py"), "w", encoding="utf-8") as handle:
            handle.write(_MAIN)
        directory = os.path.dirname(os.path.abspath(output))
        os.makedirs(directory, exist_ok=True)
        zipapp.create_archive(staging, output, interpreter=interpreter)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return output


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist", "appctl.pyz")))
