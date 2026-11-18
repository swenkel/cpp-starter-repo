#!/usr/bin/env python3
"""Generated project command runner; uses Python 3.11+ standard library only."""
import argparse
import os
from pathlib import Path
import sys

if sys.version_info < (3, 11):
    sys.exit("Python 3.11+ is required")

from lib import common as c, deps, build, gates

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup", "lock", "build", "test", "check", "seal"))
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args(argv)
    try:
        cfg = c.load()
        if cfg["environment"] == "docker" and os.environ.get("STARTER_IN_CONTAINER") != "1":
            return __import__('subprocess').call([str(c.ROOT / "scripts/compose.sh"), "run", "--rm", "--build", "-T", "dev", "python3", "scripts/project.py", *(argv if argv is not None else sys.argv[1:])], cwd=c.ROOT)
        if args.staged:
            gates.staged()
        if args.command == "seal":
            gates.seal()
        elif args.command == "lock":
            deps.lock(cfg)
        elif args.command == "setup":
            gates.toolchain(cfg)
            deps.setup(cfg)
        elif args.command == "build":
            build.build(cfg)
        elif args.command == "test":
            build.build(cfg)
            build.test(cfg)
        else:
            return gates.check(cfg)
        return 0
    except (c.Failure, OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
