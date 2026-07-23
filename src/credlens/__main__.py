"""Entry point for `python -m credlens`."""

from __future__ import annotations

import sys

from credlens.cli import main

if __name__ == "__main__":
    sys.exit(main())
