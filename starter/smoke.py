"""Opt-in real-tool matrix. Exit 2 means prerequisites unavailable, never success."""
import argparse
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from starter.answers import parse
from starter.apply import write_tree
from starter.plan import build

PROFILES = ("cli", "library", "header-only", "http", "numerical", "qt")

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key, choices in (("profile", PROFILES), ("build-system", ("cmake", "meson")), ("dependencies", ("native", "conan", "vcpkg")), ("test-runner", ("catch2", "gtest"))):
        parser.add_argument("--" + key, choices=("all", *choices), default="all")
    parser.add_argument("--environment", choices=("local", "docker"), default="local")
    parser.add_argument("--quality", choices=("strict", "balanced", "minimal"), default="strict")
    parser.add_argument("--compiler", choices=("clang", "gcc"), default="clang")
    parser.add_argument("--cpp-standard", choices=("17", "20", "23"), default="20")
    parser.add_argument("--library-type", choices=("static", "shared"), default="static")
    parser.add_argument("--qt-source", choices=("installed", "source", "provider", "image"), default="installed")
    parser.add_argument("--container-image")
    parser.add_argument("--keep", type=Path, help="retain generated projects and logs here (directory must be new)")
    parser.add_argument("--list-json", action="store_true")
    options = parser.parse_args(argv)
    dims = (("profile", PROFILES), ("build_system", ("cmake", "meson")), ("dependencies", ("native", "conan", "vcpkg")), ("test_runner", ("catch2", "gtest")))
    cells = [dict(zip((k for k, _ in dims), values)) for values in itertools.product(*(choices if getattr(options, key) == "all" else (getattr(options, key),) for key, choices in dims))]
    if options.list_json:
        print(json.dumps({"include": cells}))
        return 0
    required = ["docker"] if options.environment == "docker" else ["cmake", "ninja", "pkg-config"]
    if any(cell["build_system"] == "meson" for cell in cells) and options.environment != "docker": required.append("meson")
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        print("UNAVAILABLE: " + ", ".join(missing), file=sys.stderr)
        return 2
    if options.keep:
        options.keep.mkdir(parents=True, exist_ok=False)
        root = options.keep.resolve()
    else:
        root = Path(tempfile.mkdtemp(prefix="cpp-starter-smoke-"))
    failed = False
    try:
        for cell in cells:
            label = "-".join(cell.values())
            raw = {"name": "smoke-example", "environment": options.environment, "quality": options.quality,
                   "compiler": options.compiler, "cpp_standard": options.cpp_standard, "library_type": options.library_type,
                   "ci": "none", "git_init": "no", **cell}
            if cell["profile"] == "qt": raw["qt_source"] = options.qt_source
            if options.container_image:
                raw.update(base_image="custom", container_image=options.container_image)
            a = parse(raw)
            project = root / label
            write_tree(project, build(a), a)
            print(f"RUN {label}", flush=True)
            with (root / f"{label}.log").open("w") as log:
                for command in ("lock", "setup", "check"):
                    p = subprocess.run([sys.executable, "scripts/project.py", command], cwd=project, stdout=log, stderr=subprocess.STDOUT, check=False)
                    if p.returncode:
                        failed = True
                        print(f"FAIL {label} ({command}); log: {log.name}", flush=True)
                        break
                else:
                    print(f"PASS {label}", flush=True)
        return 1 if failed else 0
    finally:
        if not options.keep:
            if failed:
                print(f"Failure artifacts retained: {root}")
            else:
                shutil.rmtree(root)

if __name__ == "__main__":
    sys.exit(main())
