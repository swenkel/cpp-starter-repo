"""Opt-in defect injection against a disposable, fully generated project."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from starter.answers import parse
from starter.apply import write_tree
from starter.plan import build

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-system", choices=("cmake", "meson"), default="cmake")
    parser.add_argument("--keep", type=Path)
    options = parser.parse_args(argv)
    root = options.keep or Path(tempfile.mkdtemp(prefix="cpp-starter-negative-"))
    a = parse(dict(name="negative-example", build_system=options.build_system, environment="local", test_runner="gtest", ci="none", git_init="no"))
    write_tree(root, build(a), a)
    failed = False
    try:
        for command in ("lock", "setup", "check"):
            status = subprocess.run([sys.executable, "scripts/project.py", command], cwd=root, check=False)
            if status.returncode:
                print("Baseline failed; defect probes are not counted as passes.")
                return status.returncode
        source = (root / "src/core.cpp").read_text()
        cases = [
            ("format", "src/core.cpp", source.replace("if (value < 0)", "if(value<0)"), "gates.formatting(cfg)", ("clang-format",)),
            ("warnings", "src/core.cpp", source + "\nint probe() { int unused = 0; return 0; }\n", "build.build(cfg)", ("unused variable",)),
            ("clang-tidy", "src/core.cpp", source + "\nint probe() { int *p = nullptr; return *p; }\n", "gates.tidy(cfg)", ("clang-analyzer-core.NullDereference",)),
            ("cppcheck", "src/core.cpp", source + "\nint probe() { int values[1] = {0}; return values[2]; }\n", "gates.cppcheck(cfg)", ("arrayIndexOutOfBounds",)),
            ("suppression", "src/core.cpp", source + "\n// NOLINT\n", "gates.suppressions(cfg)", ("suppression",)),
            ("sanitizers", "src/core.cpp", source.replace("return -1;", "auto *values = new int[1];\n    values[-value] = 1;\n    delete[] values;\n    return -1;"), "build.build(cfg, 'sanitizer'); build.test(cfg, 'sanitizer')", ("runtime error:", "ERROR: AddressSanitizer")),
            ("coverage", "src/core.cpp", source.replace("if (value < 0)", "if (value == 42) { return 7; }\n  if (value < 0)"), "gates.coverage(cfg)", ("threshold not met", "gcovr exited")),
            ("public-header", "include/negative_example/broken.hpp", "#pragma once\ninline double *probe(int *p) { return (double *)p; }\n", "gates.tidy(cfg)", ("cppcoreguidelines-pro-type-cstyle-cast",)),
            ("seal", ".clang-tidy", (root / ".clang-tidy").read_text() + "\n", "gates.integrity(cfg)", ("gate seal differs",)),
            ("lock", "dependencies.json", (root / "dependencies.json").read_text() + "\n", "deps.verify_lock(cfg)", ("dependency manifests changed",)),
        ]
        for name, relative, changed, action, evidence in cases:
            path = root / relative
            original = path.read_bytes() if path.exists() else None
            try:
                path.write_text(changed)
                program = "import sys; sys.path.insert(0, 'scripts'); from lib import common, gates, deps, build; cfg=common.load(); " + action
                result = subprocess.run([sys.executable, "-c", program], cwd=root, text=True, capture_output=True, check=False)
                output = result.stdout + result.stderr
                (root / f"probe-{name}.log").write_text(output)
                passed = result.returncode != 0 and any(marker in output for marker in evidence)
                failed |= not passed
                print(f"{'PASS' if passed else 'FAIL'} defect detection: {name}", flush=True)
            finally:
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)
        return 1 if failed else 0
    finally:
        if not options.keep:
            shutil.rmtree(root)

if __name__ == "__main__":
    sys.exit(main())
