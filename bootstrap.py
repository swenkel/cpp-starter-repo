"""Generate a new project from this starter: ``python3 bootstrap.py``."""

import sys
from pathlib import Path

if sys.version_info < (3, 11):  # noqa: UP036
    sys.exit("bootstrap.py requires Python 3.11 or newer")

sys.dont_write_bytecode = True

from starter.cli import main

if __name__ == "__main__":
    sys.exit(main(Path(__file__).resolve().parent))
