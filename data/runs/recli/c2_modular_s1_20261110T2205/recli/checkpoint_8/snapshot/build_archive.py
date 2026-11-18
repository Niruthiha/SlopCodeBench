#!/usr/bin/env python3
"""Build the appctl distribution archive: a Python zip application (``appctl.pyz``)."""

import argparse
import os
import shutil
import sys
import tempfile
import zipapp

ROOT = os.path.dirname(os.path.abspath(__file__))
PACKAGE = "appctl_cli"
MAIN = "import sys\n\nfrom appctl_cli.app import main\n\nsys.exit(main(sys.argv[1:]))\n"


def build(target, interpreter="/usr/bin/env python3"):
    workdir = tempfile.mkdtemp(prefix="appctl-build-")
    try:
        shutil.copytree(os.path.join(ROOT, PACKAGE), os.path.join(workdir, PACKAGE),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        with open(os.path.join(workdir, "__main__.py"), "w", encoding="utf-8") as handle:
            handle.write(MAIN)
        directory = os.path.dirname(os.path.abspath(target))
        os.makedirs(directory, exist_ok=True)
        zipapp.create_archive(workdir, target, interpreter=interpreter, compressed=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=os.path.join(ROOT, "dist", "appctl.pyz"))
    args = parser.parse_args(argv)
    print(build(args.target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
