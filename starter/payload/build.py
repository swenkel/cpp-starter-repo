"""Build-system adapters with identical gate semantics."""
import json
import os
from pathlib import Path
import shlex
from . import common as c, deps

def environment(cfg, variant):
    env = os.environ.copy()
    directory = c.build_dir(cfg, variant)
    family, cc, cxx = c.compiler(cfg, variant)
    env.update(CC=cc, CXX=cxx)
    prefix = deps.qt_prefix(cfg)
    if prefix:
        env["CMAKE_PREFIX_PATH"] = prefix
        env["PKG_CONFIG_PATH"] = os.pathsep.join([str(Path(prefix) / "lib/pkgconfig"), str(Path(prefix) / "lib64/pkgconfig")])
        env["PATH"] = os.pathsep.join([str(Path(prefix) / "bin"), str(Path(prefix) / "libexec"), env["PATH"]])
    if cfg["dependencies"] == "conan":
        env["PKG_CONFIG_PATH"] = str(directory / "conan") + os.pathsep + env.get("PKG_CONFIG_PATH", "")
    if cfg["dependencies"] == "vcpkg":
        provider = json.loads((directory / "provider.json").read_text())
        root = Path(provider["prefix"])
        paths = [root / "debug/lib/pkgconfig", root / "debug/share/pkgconfig", root / "share/pkgconfig"]
        env["PKG_CONFIG_PATH"] = os.pathsep.join(str(p) for p in paths) + os.pathsep + env.get("PKG_CONFIG_PATH", "")
        env["CMAKE_PREFIX_PATH"] = str(root) + os.pathsep + env.get("CMAKE_PREFIX_PATH", "")
        env["PATH"] = os.pathsep.join([str(root / "tools/Qt6/bin"), str(root / "tools/qt6/bin"), str(root / "tools/Qt6/libexec"), env["PATH"]])
        env["QT_PLUGIN_PATH"] = str(root / "debug/Qt6/plugins")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["STARTER_SMOKE_TEST"] = "1"
    env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    # Leak detection is a separate, platform-dependent sanitizer; ASan/UBSan remain fatal.
    env["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
    if variant == "coverage" and family == "clang":
        profiles = directory / "profiles"
        profiles.mkdir(parents=True, exist_ok=True)
        env["LLVM_PROFILE_FILE"] = str(profiles / "%p-%m.profraw")
    return env

def configure(cfg, variant):
    directory = c.build_dir(cfg, variant)
    directory.mkdir(parents=True, exist_ok=True)
    family, cc, cxx = c.compiler(cfg, variant)
    env = environment(cfg, variant)
    if cfg["build_system"] == "cmake":
        args = ["cmake", "-S", c.ROOT, "-B", directory, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Debug",
                f"-DCMAKE_C_COMPILER={cc}", f"-DCMAKE_CXX_COMPILER={cxx}", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
                "-DBUILD_TESTING=ON", f"-DSTARTER_WERROR={'ON' if cfg['warnings_as_errors'] == 'yes' else 'OFF'}",
                f"-DSTARTER_COVERAGE={'ON' if variant == 'coverage' else 'OFF'}", f"-DSTARTER_SANITIZERS={'ON' if variant == 'sanitizer' else 'OFF'}"]
        if cfg["dependencies"] == "conan":
            args += [f"-DCMAKE_TOOLCHAIN_FILE={directory / 'conan/conan_toolchain.cmake'}"]
        if cfg["dependencies"] == "vcpkg":
            provider = json.loads((directory / "provider.json").read_text())
            args += [f"-DCMAKE_TOOLCHAIN_FILE={provider['root']}/scripts/buildsystems/vcpkg.cmake", "-DVCPKG_MANIFEST_INSTALL=OFF",
                     f"-DVCPKG_TARGET_TRIPLET={provider['triplet']}", f"-DVCPKG_HOST_TRIPLET={provider['triplet']}",
                     f"-DVCPKG_INSTALLED_DIR={directory / 'vcpkg_installed'}", f"-DVCPKG_OVERLAY_TRIPLETS={directory / 'triplets'}"]
        c.run(args, env=env)
    else:
        native = directory / "native.ini"
        native.write_text(f"[binaries]\nc = {cc!r}\ncpp = {cxx!r}\n[properties]\n[built-in options]\ncpp_std = 'c++{cfg['cpp_standard']}'\n")
        args = ["meson", "setup", directory, c.ROOT, "--backend=ninja", "--buildtype=debug", "--wrap-mode=nodownload",
                "--native-file", native, f"-Dgate_werror={str(cfg['warnings_as_errors'] == 'yes').lower()}",
                f"-Dgate_coverage={str(variant == 'coverage').lower()}", f"-Dgate_sanitizers={str(variant == 'sanitizer').lower()}"]
        # Clang's ASan runtime is linked by the executable, not shared libraries.
        args += [f"-Db_lundef={str(not (variant == 'sanitizer' and family == 'clang')).lower()}"]
        if (directory / "meson-private/coredata.dat").exists():
            args += ["--reconfigure", "--clearcache"]
        if cfg["dependencies"] == "conan":
            args += ["--native-file", directory / "conan/conan_meson_native.ini", "--wrap-mode=nofallback"]
        c.run(args, env=env)
    database = directory / "compile_commands.json"
    if not database.is_file():
        raise c.Failure("build system did not produce a compilation database")
    verify_provider(cfg, variant)

def verify_provider(cfg, variant):
    """Reject accidental discovery of system packages in managed-provider modes."""
    if cfg["dependencies"] == "native":
        return
    directory = c.build_dir(cfg, variant)
    prefix = directory / "conan" if cfg["dependencies"] == "conan" else Path(json.loads((directory / "provider.json").read_text())["prefix"])
    names = [("Catch2", "catch2-with-main")] if cfg["test_runner"] == "catch2" else [("GTest", "gtest_main")]
    if cfg["profile"] == "numerical": names.append(("Eigen3", "eigen3"))
    if cfg["profile"] == "http": names.append(("httplib", "cpp-httplib"))
    if cfg["profile"] == "qt" and cfg["qt_source"] == "provider": names.append(("Qt6", "Qt6Widgets"))
    if cfg["build_system"] == "cmake":
        cache = {}
        for line in (directory / "CMakeCache.txt").read_text().splitlines():
            if "=" in line and ":" in line and not line.startswith(("//", "#")):
                name, value = line.split("=", 1)
                cache[name.split(":", 1)[0]] = value
        locations = [(name, cache.get(name + "_DIR", "")) for name, _ in names]
    else:
        locations = [(name, c.run(["pkg-config", "--path", module], env=environment(cfg, variant), capture=True).strip()) for name, module in names]
    for name, location in locations:
        if not location or not Path(location).resolve().is_relative_to(prefix.resolve()):
            raise c.Failure(f"{name} resolved outside the selected {cfg['dependencies']} provider: {location}")

def build(cfg, variant="debug"):
    deps.ready(cfg, variant)
    configure(cfg, variant)
    directory = c.build_dir(cfg, variant)
    jobs = os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL", "2")
    args = ["cmake", "--build", directory, "--parallel", jobs] if cfg["build_system"] == "cmake" else ["meson", "compile", "-C", directory, "-j", jobs]
    c.run(args, env=environment(cfg, variant))

def test(cfg, variant="debug"):
    directory = c.build_dir(cfg, variant)
    env = environment(cfg, variant)
    args = ["ctest", "--test-dir", directory, "--output-on-failure", "--no-tests=error"] if cfg["build_system"] == "cmake" else ["meson", "test", "-C", directory, "--print-errorlogs", "--no-rebuild"]
    c.run(args, env=env)
    from .smoke import application
    application(cfg, directory, env)

def compilation_database(cfg, variant="analysis"):
    directory = c.build_dir(cfg, variant)
    entries = json.loads((directory / "compile_commands.json").read_text())
    first_party = []
    for entry in entries:
        path = Path(entry["file"])
        if not path.is_absolute():
            path = Path(entry["directory"]) / path
        path = path.resolve()
        if any(path.is_relative_to(c.ROOT / name) for name in ("src", "tests", "include")):
            entry["file"] = str(path)
            first_party.append(entry)
    if not first_party:
        raise c.Failure("no first-party translation units in compilation database")
    # Every maintained implementation must belong to a target.
    known = {Path(e["file"]) for e in first_party}
    missing = [p for p in c.source_files() if p.suffix in {".c", ".cpp", ".cc", ".cxx"} and p not in known and p != c.ROOT / "tests/consumer.cpp"]
    if missing:
        raise c.Failure("source files missing from build: " + ", ".join(str(p) for p in missing))
    return directory, first_party

def consumer(cfg):
    directory = c.build_dir(cfg, "debug")
    prefix = directory / "install"
    env = environment(cfg, "debug")
    if cfg["build_system"] == "cmake":
        c.run(["cmake", "--install", directory, "--prefix", prefix], env=env)
        ns = cfg["name"].replace("-", "_")
        consumer_source = directory / "consumer-project"
        consumer_source.mkdir(exist_ok=True)
        (consumer_source / "CMakeLists.txt").write_text(
            f'cmake_minimum_required(VERSION 3.28)\nproject(Consumer LANGUAGES CXX)\nfind_package({ns} CONFIG REQUIRED)\nadd_executable(consumer "{c.ROOT / "tests/consumer.cpp"}")\ntarget_link_libraries(consumer PRIVATE {ns}::{ns})\n')
        destination = directory / "consumer-build"
        c.run(["cmake", "-S", consumer_source, "-B", destination, "-G", "Ninja", f"-DCMAKE_PREFIX_PATH={prefix}", f"-DCMAKE_CXX_COMPILER={c.compiler(cfg, 'debug')[2]}"], env=env)
        c.run(["cmake", "--build", destination], env=env)
        c.run([destination / "consumer"], env=env)
        return
    else:
        # DESTDIR leaves the project build configuration unchanged.
        c.run(["meson", "install", "-C", directory, "--no-rebuild", "--destdir", prefix], env=env)
        prefix /= "usr/local"
    ns = cfg["name"].replace("-", "_")
    binary = directory / "consumer"
    descriptors = list(prefix.rglob(f"{ns}.pc"))
    if len(descriptors) != 1:
        raise c.Failure("installed pkg-config metadata is missing or ambiguous")
    env["PKG_CONFIG_PATH"] = str(descriptors[0].parent)
    env["PKG_CONFIG_SYSROOT_DIR"] = str(directory / "install")
    flags = shlex.split(c.run(["pkg-config", "--cflags", "--libs", ns], env=env, capture=True))
    args = [c.compiler(cfg, "debug")[2], f"-std=c++{cfg['cpp_standard']}", c.ROOT / "tests/consumer.cpp", "-o", binary, *flags]
    if cfg["profile"] != "header-only":
        libraries = sorted(prefix.rglob(f"lib{ns}.*"))
        if not libraries:
            raise c.Failure("installed library not found")
        lib = next((p for p in libraries if p.suffix == ".a"), libraries[0])
        args += [f"-Wl,-rpath,{lib.parent}"]
    c.run(args, env=env)
    c.run([binary], env=env)
