"""Pure rendering: decide every output before performing any writes."""
from dataclasses import dataclass
import json
from pathlib import Path
from starter import render_build, render_code, render_config, render_policy

@dataclass(frozen=True)
class PlannedFile:
    path: str
    content: str
    mode: int = 0o644

COMPOSE = '''#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")/.."
LOCAL_UID=$(id -u)
LOCAL_GID=$(id -g)
export LOCAL_UID LOCAL_GID
exec docker compose "$@"
'''
CHECK = '''#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")/.."
command=check
if [ "${1:-}" = --seal ]; then command=seal; shift; fi
exec python3 scripts/project.py "$command" "$@"
'''
HOOK = '''#!/bin/sh
set -eu
exec "$(git rev-parse --show-toplevel)/scripts/check.sh" --staged
'''

def readme(a):
    return f'''# {a.name}

C++{a.cpp_standard} {a.profile} using {a.build_system}, {a.dependencies}, and {a.test_runner}.

## Getting started

Generation installs nothing. Development requires Python 3.11+ and
{'Docker with Compose. All commands below dispatch into the container.' if a.docker else 'the tools listed in dependencies.json. `sh scripts/install-tools.sh` provisions Ubuntu/Debian or Homebrew; it is an explicit installation command, never run by checks.'}

```sh
python3 scripts/project.py lock
python3 scripts/project.py setup
scripts/check.sh
```

Commit dependency locks after reviewing them. `setup` downloads/builds dependencies;
`check` never updates locks or downloads dependency archives. An interrupted setup
can be rerun. Changing build/compiler/gate settings requires setup again.
Conan locks can vary by platform: run `lock` on each supported platform and commit
the merged conan.lock and dependencies.lock.json. CI never creates or updates locks.

The command runner also exposes `build`, `test`, and human-only `seal` commands.
The native hook runs the same checks and rejects unstaged or untracked changes.
Enable it manually with `git config core.hooksPath .githooks` if Git initialization
was disabled. No initial commit is created.

## Toolchain and dependencies

Use LLVM 21 (including clang-tidy, clang-format, and llvm-cov) or GCC 14/15 on Linux.
macOS uses upstream LLVM 21 from Homebrew, including when Linux selects GCC.
Put `.tools/bin` and the selected LLVM installation's `bin` directory on PATH.
The project uses CMake >=3.28, Meson >=1.4 when selected, Ninja, and pkg-config.
Tool versions and source hashes are recorded in dependencies.json. Checks fail
when required tools are missing. Python is required for tooling, not by the C++ library.

Native source archives are pinned by SHA256. Conan uses explicit recipe versions
and lockfiles. Provider versions can differ from native archives: cpp-httplib uses
0.20.1 with Conan because ConanCenter has no 0.20.0 recipe. vcpkg uses the pinned
baseline and tool commit; its package versions follow that baseline. VCPKG_ROOT may
point to an existing checkout at the exact recorded revision. Other checkouts are
never changed. Setup otherwise creates a project-local vcpkg checkout.

Set `CMAKE_BUILD_PARALLEL_LEVEL` to control parallelism (default 2).
For offline setup, pre-populate archives via `STARTER_SOURCE_CACHE`; hashes still
apply. Native Meson wraps and CMake FetchContent use the same reviewed archives.

## Qt and application behavior

Qt selection: {a.qt_source if a.profile == 'qt' else 'not applicable'}.
For installed/image Qt, set QT_ROOT when the SDK is outside standard search paths.
In containers use `scripts/compose.sh run --rm -e QT_ROOT=/opt/Qt dev ...`
or the image's own QT_ROOT environment setting.
Qt >=6.8 is required. Source mode builds the pinned shared QtBase release.
For local Qt provisioning, pass `qt` to scripts/install-tools.sh for an installed
SDK, or `qt-build` for source/provider platform prerequisites.
Provider mode gets Qt exclusively from Conan/vcpkg. A supplied image must already
contain compatible tools and Qt; setup validates it without guessing its package manager.
Container GUI tests use the offscreen platform. Run native Qt builds to use the desktop GUI.
The HTTP example prints its dynamically selected localhost port and exposes /health;
SIGINT/SIGTERM shuts it down cleanly. This is a starter, not a production server.

## Quality policy

Strictness and guideline families are independent choices. The presets initialize
gate switches; explicit answers override them. Gate switches and thresholds live
in gates.toml; native .clang-tidy and .clang-format files control tool details.
The selected guideline families implement a documented subset, not complete
Core Guidelines/CERT/Google/LLVM compliance. No commercial tooling is required.

Checks analyze project source, tests, and independent public-header probes; dependencies
and generated sources are excluded. Coverage measures first-party source and headers:
LLVM source coverage for Clang, gcovr for GCC with unreachable/exception branches excluded.
Qt's GUI smoke executable tests the shared window implementation; the native main
wrapper remains visible as unexecuted in coverage reports. ASan/UBSan builds are
separate; LeakSanitizer is disabled for cross-platform consistency.
Reports are written to reports/. Missing/blocked checks are failures, never passes.

Suppression policy: {a.suppressions}. Narrow examples:
`// NOLINTNEXTLINE(bugprone-branch-clone) -- reason: API compatibility`
or `// cppcheck-suppress unusedFunction -- reason: exported API`.
Blanket suppressions and format/coverage disabling require unrestricted policy.

Gate seals and tool deny rules provide tamper evidence, not a sandbox. Review gate
diffs. After an explicitly requested policy change, a human runs
`scripts/check.sh --seal`. This does not resolve build/dependency issues.

## Generated choices

```json
{json.dumps(a.values, indent=2, sort_keys=True)}
```
'''

def build(a):
    contents = {"gates.toml": render_config.toml(a.values), "dependencies.json": json.dumps(render_config.catalog(a), indent=2) + "\n",
                ".clang-tidy": render_config.tidy(a), ".clang-format": render_config.clang_format(a),
                "README.md": readme(a), "AGENTS.md": render_policy.agents(a),
                "CLAUDE.md": "Read and follow AGENTS.md.\n\n@AGENTS.md\n", "GEMINI.md": "Read and follow AGENTS.md.\n\n@AGENTS.md\n",
                ".gitignore": "build/\n.cache/\n.tools/\nreports/\n__pycache__/\n*.pyc\nsubprojects/*/\n!subprojects/packagefiles/\n!subprojects/packagefiles/**\n.env\n.env.*\n!.env.example\nCMakeUserPresets.json\n",
                ".dockerignore": "**\n!Dockerfile\n!scripts/\n!scripts/install-tools.sh\n",
                "scripts/check.sh": CHECK, ".githooks/pre-commit": HOOK, "scripts/install-tools.sh": render_config.INSTALL_TOOLS}
    contents.update(render_build.files(a))
    contents.update(render_code.files(a))
    contents.update(render_config.providers(a))
    payload = Path(__file__).parent / "payload"
    for path in payload.glob("*.py"):
        dest = "scripts/project.py" if path.name == "project.py" else "scripts/lib/" + path.name
        contents[dest] = path.read_text()
    if a.guard != "policy":
        contents[".claude/settings.json"] = render_policy.settings(a)
    if a.docker:
        contents.update({"compose.yaml": render_config.compose(a), "scripts/compose.sh": COMPOSE})
        if a.base_image != "custom":
            contents["Dockerfile"] = render_config.dockerfile(a)
    if a.ci == "github":
        contents[".github/workflows/check.yaml"] = render_config.workflow(a)
    return tuple(PlannedFile(name, content, 0o755 if name.endswith(".sh") or name in {"scripts/project.py", ".githooks/pre-commit"} else 0o644) for name, content in sorted(contents.items()))
