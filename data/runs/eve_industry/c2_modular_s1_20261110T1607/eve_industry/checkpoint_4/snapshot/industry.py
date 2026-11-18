#!/usr/bin/env python3
"""Entry point:
    python industry.py recipe <Product or Blueprint name> --sde <SDE directory>
        [--material-efficiency/-me <0-10>] [--time-efficiency/-te <even 0-20>] [--display-waste/-waste]
    python industry.py invention <Product or Blueprint name> --sde <SDE directory> [--skill <1-5>]
    python industry.py plan <Build string> --config <YAML config> --sde <SDE directory> --output <dir>
"""

import sys

from eve_industry.cli import main

if __name__ == "__main__":
    sys.exit(main())
