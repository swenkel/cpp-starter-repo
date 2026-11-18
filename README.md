# cpp-starter-repo

Generate a configurable C++ project, then safely remove the starter.
Python 3.11+ and its standard library are sufficient to generate projects offline.
The architecture follows the adjacent python-starter-repo, with C++ build and quality adapters.

```sh
python3 bootstrap.py
python3 bootstrap.py --answers /path/to/answers.json --output /path/to/new-project
python3 bootstrap.py --answers /path/to/answers.json --dry-run --show
```

Without `--output`, generation removes the starter and its Git history after
checking its manifest and clean checkout. Modified starters and linked worktrees
must use an external output directory. Unknown files prevent self-removal.
Interactive replacement requires confirmation; an answers file authorizes it.

## Choices

| Key | Values (first is default unless preset-dependent) |
| --- | --- |
| name | Required: lowercase words joined by hyphens |
| profile | cli, library, header-only, http, numerical, qt |
| build_system | cmake, meson |
| cpp_standard | 20, 17, 23 |
| dependencies | native, conan, vcpkg; all combinations supported |
| environment | docker, local |
| compiler | clang, gcc (macOS uses LLVM Clang) |
| test_runner | catch2, gtest |
| quality | strict, balanced, minimal |
| guidelines | Array: core, cert, bugprone, modernize, readability, performance, portability |
| style | none, google, llvm |
| tidy_add / tidy_remove | Arrays of exact checks; removal wins |
| tidy_options | Map of check option names to string values |
| clang_format / clang_tidy / cppcheck / warnings_as_errors | yes, no |
| cppcheck_categories | Array: warning, style, performance, portability, unusedFunction |
| coverage | 90, 80, 100, 0 (off) |
| sanitizers | address,undefined; none |
| suppressions | none, narrow, unrestricted |
| format_style / line_length | LLVM or Google; 100, 80, 120 |
| library_type | static, shared |
| base_image | ubuntu:26.04, debian:trixie, custom |
| container_image | Required image reference for custom base |
| qt_source | Required for Qt: provider, installed, source, image |
| guard | seal, config, policy |
| test_approval | yes, no |
| agent_git_add / agent_git_commit / agent_git_push | no, yes |
| ci | github, none |
| git_init | yes, no |

Scalar answers are strings. Lists and `tidy_options` are the documented exceptions.
Omitted settings use defaults; explicit overrides win over quality presets.

```json
{
  "name": "example-library",
  "profile": "library",
  "build_system": "meson",
  "dependencies": "native",
  "environment": "local",
  "quality": "balanced",
  "guidelines": ["core", "cert", "performance"],
  "coverage": "90"
}
```

Minimal runs builds/tests with compiler warnings. Balanced adds formatting,
warnings-as-errors, clang-tidy, and cppcheck. Strict also enables ASan/UBSan and
90% branch coverage. Every optional gate remains individually selectable.
Rule bundles are explicit reviewed subsets, not full guideline compliance.

Qt users choose an installed SDK, a pinned source build, Conan/vcpkg, or an
existing container image. Provider mode requires Conan/vcpkg; image mode requires
a custom Docker image. LLVM 21, GCC 14/15, and Qt >=6.8 are the supported baseline.

## Generated project

The generated README records selections, setup, tool requirements, and limitations.
One command runner provides setup, lock, build, test, check, and seal operations.
Hooks and CI run the same gates. Seals and agent deny rules are tamper evidence,
not a sandbox. Generated projects receive no project license; the starter is MIT licensed.

Dependency setup may access the network; generation never does. Review and commit
locks before CI. CMake and Meson use Ninja. Docker builds Linux artifacts, including
on macOS; native macOS is a separate CI job. Native Windows, embedded targets,
CUDA, C++ modules, commercial compliance, and vulnerability auditing are outside v1.

`python3 bootstrap.py --check-images` compares built-in image pins with newer matching registry tags without
generating anything. Custom images are not queried; tags are not digest pins.

## Develop and validate

```sh
python3 -m unittest
python3 -m starter.manifest
python3 -m starter.smoke --help
```

Refresh the manifest only after reviewing intentional changes. Unit tests are offline;
integration smoke tests explicitly download dependencies and require the selected tools.
Missing prerequisites produce a nonzero unavailable result, not a pass.

Examples of targeted integration checks:

```sh
python3 -m starter.smoke --profile cli --dependencies native --test-runner gtest
python3 -m starter.smoke --profile qt --qt-source provider --dependencies conan
python3 -m starter.smoke --profile qt --qt-source source --dependencies native
python3 -m starter.smoke --profile qt --qt-source image --environment docker --container-image registry.example/qt:tag
python3 -m starter.smoke --profile library --compiler gcc --cpp-standard 23
python3 -m starter.smoke --profile library --library-type shared --dependencies native --test-runner gtest
python3 -m starter.negative --build-system cmake
```

The manually dispatched starter workflow defines all 72 template/build/provider/test
combinations on Linux and macOS. This main matrix uses installed Qt; additional
jobs cover Qt providers, pinned Qt source builds, shared libraries, and defect
injection on both platforms. A Linux job builds a Qt SDK image locally and checks
both build systems through the custom-image path; it never publishes the image.
Regular pushes run the offline suite on both platforms with Python 3.11 and 3.13.
