#!/usr/bin/env python3
"""Entry point:
    python industry.py recipe <Product or Blueprint name> --sde <SDE directory>
    python industry.py invention <Product or Blueprint name> --sde <SDE directory> [--skill <1-5>]
"""

import sys

from eve_industry.cli import main

if __name__ == "__main__":
    sys.exit(main())
