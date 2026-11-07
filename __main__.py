"""
Allows the package to be run directly:

    python -m stock_bot [options]

All logic lives in cli.py; this file is just the entry point.
"""

import sys

from cli import main

sys.exit(main())
