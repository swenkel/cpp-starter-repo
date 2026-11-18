"""Project configuration, pins, environment, and CI rendering."""
import json
from starter import versions
from starter.payload.schema import checks

def toml(settings):
    lines = []
    for key, value in sorted(settings.items()):
        if isinstance(value, dict):
            continue
        lines.append(f"{key} = {json.dumps(value)}")
    lines += ["", "[tidy_options]"]
    lines += [f"{json.dumps(k)} = {json.dumps(v)}" for k, v in sorted(settings["tidy_options"].items())]
    return "\n".join(lines) + "\n"

def catalog(a):
    return {"packages": versions.selected(a), "tools": versions.TOOLS, "vcpkg_revision": versions.VCPKG_REVISION,
            "qt": {"version": "6.8.3", "directory": "qtbase-everywhere-src-6.8.3", "url": "https://download.qt.io/archive/qt/6.8/6.8.3/submodules/qtbase-everywhere-src-6.8.3.tar.xz", "sha256": "56001b905601bb9023d399f3ba780d7fa940f3e4861e496a7c490331f49e0b80"}}

def tidy(a):
    # JSON is valid YAML and allows stdlib-only validation.
    return json.dumps({"Checks": "-*," + ",".join(checks(a.values)), "WarningsAsErrors": "*", "HeaderFilterRegex": "(^|/)(include|src|tests)/", "SystemHeaders": False, "InheritParentConfig": False, "CheckOptions": a.tidy_options}, indent=2) + "\n"

def clang_format(a):
    return f"BasedOnStyle: {a.format_style}\nColumnLimit: {a.line_length}\nIndentWidth: 2\nPointerAlignment: Right\nDerivePointerAlignment: false\nSortIncludes: Never\nSpacesBeforeTrailingComments: 1\nAllowShortFunctionsOnASingleLine: Empty\n"

def providers(a):
    pins = versions.selected(a)
    files = {}
    if a.dependencies == "conan":
        requires = [p["conan"] for p in pins.values()]
        if a.profile == "qt" and a.qt_source == "provider":
            requires.append("qt/6.8.3")
        generators = '("CMakeDeps", "CMakeToolchain")' if a.build_system == "cmake" else '("PkgConfigDeps", "MesonToolchain")'
        files["conanfile.py"] = 'from conan import ConanFile\n\nclass ProjectDependencies(ConanFile):\n    settings = "os", "arch", "compiler", "build_type"\n    requires = ' + repr(tuple(requires)) + '\n    generators = ' + generators + '\n'
        if a.profile == "qt" and a.qt_source == "provider":
            files["conanfile.py"] += '    default_options = {"qt/*:shared": True, "qt/*:gui": True, "qt/*:widgets": True, "qt/*:openssl": False, "qt/*:with_pq": False, "qt/*:with_odbc": False, "qt/*:with_sqlite3": False, "qt/*:with_icu": False, "qt/*:with_md4c": False, "qt/*:with_brotli": False, "qt/*:with_openal": False, "harfbuzz/*:with_glib": False, "xkbcommon/*:with_wayland": False}\n'
    if a.dependencies == "vcpkg":
        ports = [p["port"] for p in pins.values()]
        if a.profile == "qt" and a.qt_source == "provider":
            ports.append({"name": "qtbase", "default-features": False, "features": ["widgets", "gui", "thread"]})
            ports.append({"name": "qtbase", "default-features": False, "features": ["xcb"], "platform": "linux"})
        files["vcpkg.json"] = json.dumps({"name": a.name, "version-string": "0.1.0", "dependencies": ports, "builtin-baseline": versions.VCPKG_REVISION}, indent=2) + "\n"
    return files

INSTALL_TOOLS = '''#!/bin/sh
# Explicit developer/CI provisioning; never invoked by the gate runner.
set -eu
if [ "$(uname -s)" = Darwin ]; then
  brew install llvm@21 cmake ninja meson pkgconf cppcheck python@3.13
  if [ "${1:-}" = qt ]; then brew install qt; fi
  echo 'Add $(brew --prefix llvm@21)/bin and .tools/bin to PATH.'
else
  SUDO=""
  if [ "$(id -u)" != 0 ]; then SUDO=sudo; fi
  $SUDO apt-get update
  $SUDO apt-get install -y ca-certificates curl wget gnupg lsb-release git build-essential cmake ninja-build pkg-config python3 python3-venv meson cppcheck autoconf automake libtool zip unzip
  if ! apt-cache show clang-21 >/dev/null 2>&1; then
    llvm_installer=$(mktemp)
    curl -fsSL https://apt.llvm.org/llvm.sh -o "$llvm_installer"
    $SUDO bash "$llvm_installer" 21 all
    rm -f "$llvm_installer"
  fi
  $SUDO apt-get install -y clang-21 clang-tidy-21 clang-format-21 llvm-21 libclang-rt-21-dev
  case "${1:-}" in
    qt|qt-build)
      $SUDO apt-get install -y libgl1-mesa-dev libegl-dev libxkbcommon-dev libfontconfig1-dev libfreetype-dev libx11-dev libx11-xcb-dev libxcb1-dev libxcb-cursor-dev libxcb-xinput-dev libxkbcommon-x11-dev libdbus-1-dev
      # Conan's xorg/system recipe checks the full X11 development interface.
      $SUDO apt-get install -y libfontenc-dev libice-dev libsm-dev libxau-dev libxaw7-dev libxcomposite-dev libxcursor-dev libxdamage-dev libxdmcp-dev libxext-dev libxfixes-dev libxi-dev libxinerama-dev libxkbfile-dev libxmu-dev libxmuu-dev libxpm-dev libxrandr-dev libxrender-dev libxres-dev libxss-dev libxt-dev libxtst-dev libxv-dev libxxf86vm-dev libxcb-glx0-dev libxcb-render0-dev libxcb-render-util0-dev libxcb-xkb-dev libxcb-icccm4-dev libxcb-image0-dev libxcb-keysyms1-dev libxcb-randr0-dev libxcb-shape0-dev libxcb-sync-dev libxcb-xfixes0-dev libxcb-xinerama0-dev libxcb-dri3-dev uuid-dev libxcb-dri2-0-dev libxcb-present-dev libxcb-composite0-dev libxcb-ewmh-dev libxcb-res0-dev libxcb-util-dev xkb-data
      ;;
  esac
  if [ "${1:-}" = qt ]; then $SUDO apt-get install -y qt6-base-dev qt6-base-dev-tools; fi
fi
python3 -m venv .tools
.tools/bin/python -m pip install 'gcovr==8.6' 'conan==2.26.2'
'''

def dockerfile(a):
    qt = (" qt" if a.qt_source == "installed" else " qt-build") if a.profile == "qt" else ""
    return f'''FROM {a.base_image}
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /opt/starter
COPY scripts/install-tools.sh ./install-tools.sh
RUN sh install-tools.sh{qt}
ENV PATH="/opt/starter/.tools/bin:/usr/lib/llvm-21/bin:$PATH"
ENV STARTER_IN_CONTAINER=1
WORKDIR /workspace
'''

def compose(a):
    service = f"    image: {json.dumps(a.container_image)}\n" if a.base_image == "custom" else "    build: .\n"
    return "services:\n  dev:\n" + service + '''    working_dir: /workspace
    user: "${LOCAL_UID:-1000}:${LOCAL_GID:-1000}"
    environment:
      STARTER_IN_CONTAINER: "1"
      HOME: /workspace/.cache/home
      CONAN_HOME: /workspace/.cache/conan
      QT_QPA_PLATFORM: offscreen
    volumes:
      - .:/workspace
    command: ["python3", "scripts/project.py", "check"]
'''

def workflow(a):
    qt = (" qt" if a.qt_source in {"installed", "image"} else " qt-build") if a.profile == "qt" else ""
    text = """name: Quality
on: [push, pull_request]
permissions:
  contents: read
jobs:
  native:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-24.04
            container: ubuntu:26.04
          - os: macos-15
    runs-on: ${{ matrix.os }}
    container: ${{ matrix.container }}
    env:
      CONAN_HOME: ${{ github.workspace }}/.cache/conan
    steps:
      - uses: actions/checkout@v4
      - uses: actions/cache@v4
        with:
          path: .cache
          key: dependencies-${{ runner.os }}-${{ hashFiles('dependencies.json', '*lock*', 'vcpkg.json', 'conanfile.py') }}
      - run: sh scripts/install-tools.shQT_ARG
      - name: Run selected gates natively
        env:
          STARTER_IN_CONTAINER: '1'
        run: |
          export PATH="$PWD/.tools/bin:/usr/lib/llvm-21/bin:$PATH"
          if [ "$(uname -s)" = Darwin ]; then
            export PATH="$(brew --prefix llvm@21)/bin:$PATH"
            export QT_ROOT="$(brew --prefix qt 2>/dev/null || true)"
          fi
          python3 scripts/project.py setup
          python3 scripts/project.py check
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: reports-${{ matrix.os }}
          path: |
            reports/
            build/**/Testing/Temporary/LastTest.log
            build/**/meson-logs/testlog.txt
""".replace("QT_ARG", qt)
    if a.docker:
        text += """  container:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - run: scripts/compose.sh run --rm --build -T dev python3 scripts/project.py setup
      - run: scripts/check.sh
"""
    return text
