"""Explicit network setup and dependency locking. Checks never resolve updates."""
import json
import os
from pathlib import Path
import platform
import shutil
import tarfile
import urllib.request
from . import common as c

def manifests():
    names = ["dependencies.json", "conanfile.py", "vcpkg.json", "vcpkg-configuration.json"]
    return {name: c.digest(c.ROOT / name) for name in names if (c.ROOT / name).is_file()}

def lock(cfg):
    if cfg["dependencies"] == "conan":
        locks = []
        existing = c.ROOT / "conan.lock"
        if existing.exists():
            locks.append(existing)
        for variant in c.variants(cfg):
            directory = c.build_dir(cfg, variant)
            profile = conan_profile(cfg, variant)
            path = directory / "resolved.lock"
            c.run(["conan", "lock", "create", ".", "-pr:h", profile, "-pr:b", profile,
                   "-s:b", "build_type=Release", "--lockfile=", f"--lockfile-out={path}"])
            locks.append(path)
        c.run(["conan", "lock", "merge", *[f"--lockfile={p}" for p in locks], f"--lockfile-out={existing}"])
    snapshot = {"manifests": manifests()}
    if (c.ROOT / "conan.lock").exists():
        snapshot["conan_lock"] = c.digest(c.ROOT / "conan.lock")
    c.write_json(c.ROOT / "dependencies.lock.json", snapshot)

def verify_lock(cfg):
    path = c.ROOT / "dependencies.lock.json"
    if not path.is_file():
        raise c.Failure("dependency lock is missing; run scripts/project.py lock and commit the result")
    snapshot = json.loads(path.read_text())
    if snapshot.get("manifests") != manifests():
        raise c.Failure("dependency manifests changed; review and run scripts/project.py lock")
    if cfg["dependencies"] == "conan":
        path = c.ROOT / "conan.lock"
        if not path.is_file() or snapshot.get("conan_lock") != c.digest(path):
            raise c.Failure("Conan lock missing or changed; run the explicit lock command")

def download(url, checksum, target):
    target = Path(target)
    if target.exists():
        if c.digest(target) != checksum:
            raise c.Failure(f"checksum mismatch: {target}; remove the corrupt cache explicitly")
        return
    if not url.startswith("https://"):
        raise c.Failure("dependency downloads require HTTPS")
    target.parent.mkdir(parents=True, exist_ok=True)
    cached = os.environ.get("STARTER_SOURCE_CACHE")
    shared = (Path(cached) / checksum) if cached else None
    if shared is not None and shared.is_file():
        data = shared.read_bytes()
    elif cached and (Path(cached) / target.name).is_file():
        data = (Path(cached) / target.name).read_bytes()
    else:
        with urllib.request.urlopen(url, timeout=120) as response:
            if not response.url.startswith("https://"):
                raise c.Failure("dependency redirected away from HTTPS")
            data = response.read()
    import hashlib
    if hashlib.sha256(data).hexdigest() != checksum:
        raise c.Failure(f"checksum mismatch for {url}")
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)
    if cached:
        shared = Path(cached) / checksum
        shared.parent.mkdir(parents=True, exist_ok=True)
        if not shared.exists():
            shared.write_bytes(data)

def conan_profile(cfg, variant):
    family, cc, cxx = c.compiler(cfg, variant)
    version = c.version_at_least(cxx, "14" if family == "gcc" else "21")[0]
    arch = "armv8" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
    libcxx = "libc++" if platform.system() == "Darwin" else "libstdc++11"
    directory = c.build_dir(cfg, variant)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "conan.profile"
    # Qt requires the compiler's INT128 extension while building its own library.
    # Keep the root project's standard strict; scope GNU mode to the Qt package.
    qt_setting = f"qt/*:compiler.cppstd=gnu{cfg['cpp_standard']}\n" if cfg["profile"] == "qt" and cfg["qt_source"] == "provider" else ""
    path.write_text(f"[settings]\nos={'Macos' if platform.system() == 'Darwin' else 'Linux'}\narch={arch}\ncompiler={family}\ncompiler.version={version}\ncompiler.libcxx={libcxx}\ncompiler.cppstd={cfg['cpp_standard']}\nbuild_type=Debug\n{qt_setting}[conf]\ntools.build:compiler_executables={json.dumps({'c': cc, 'cpp': cxx})}\n")
    jobs = int(os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL", "2"))
    if jobs < 1:
        raise c.Failure("CMAKE_BUILD_PARALLEL_LEVEL must be a positive integer")
    with path.open("a") as stream:
        stream.write(f"tools.build:jobs={jobs}\n")
    return path

def vcpkg_root():
    return Path(os.environ.get("VCPKG_ROOT", str(c.ROOT / ".cache/vcpkg"))).resolve()

def ensure_vcpkg():
    root = vcpkg_root()
    revision = c.catalog()["vcpkg_revision"]
    if not root.exists():
        if "VCPKG_ROOT" in os.environ:
            raise c.Failure("VCPKG_ROOT must point to an existing checkout")
        c.run(["git", "clone", "https://github.com/microsoft/vcpkg.git", root])
        c.run(["git", "checkout", "--detach", revision], cwd=root)
    actual = c.run(["git", "rev-parse", "HEAD"], cwd=root, capture=True).strip()
    if actual != revision:
        raise c.Failure(f"vcpkg must be checked out at {revision}; external checkouts are never modified")
    if not (root / "vcpkg").exists():
        c.run(["sh", root / "bootstrap-vcpkg.sh", "-disableMetrics"], cwd=root)
    return root

def vcpkg_install(cfg, variant):
    root = ensure_vcpkg()
    directory = c.build_dir(cfg, variant)
    family, cc, cxx = c.compiler(cfg, variant)
    native = c.machine_triplet()
    # Overlay triplets make compiler choice explicit in vcpkg's ABI cache.
    triplet = f"starter-{native}-{family}"
    overlays = directory / "triplets"
    overlays.mkdir(parents=True, exist_ok=True)
    toolchain = overlays / "compiler.cmake"
    system = "osx" if platform.system() == "Darwin" else "linux"
    toolchain.write_text(f'set(CMAKE_C_COMPILER "{cc}")\nset(CMAKE_CXX_COMPILER "{cxx}")\ninclude("{root.as_posix()}/scripts/toolchains/{system}.cmake")\n')
    (overlays / f"{triplet}.cmake").write_text(
        f'set(VCPKG_TARGET_ARCHITECTURE {native.split("-")[0]})\nset(VCPKG_CRT_LINKAGE dynamic)\nset(VCPKG_LIBRARY_LINKAGE dynamic)\nset(VCPKG_CMAKE_SYSTEM_NAME {"Darwin" if platform.system() == "Darwin" else "Linux"})\nset(VCPKG_CHAINLOAD_TOOLCHAIN_FILE "${{CMAKE_CURRENT_LIST_DIR}}/compiler.cmake")\n')
    install = directory / "vcpkg_installed"
    c.run([root / "vcpkg", "install", f"--triplet={triplet}", f"--host-triplet={triplet}", f"--overlay-triplets={overlays}", f"--x-install-root={install}", "--disable-metrics"])
    c.write_json(directory / "provider.json", {"prefix": str(install / triplet), "triplet": triplet, "root": str(root)})

def qt_prefix(cfg):
    if cfg["profile"] != "qt" or cfg["qt_source"] == "provider":
        return ""
    if cfg["qt_source"] == "source":
        return str(c.ROOT / ".cache/qt/install")
    return os.environ.get("QT_ROOT", "")

def prepare_qt(cfg):
    if cfg["profile"] != "qt" or cfg["qt_source"] != "source":
        return
    pin = c.catalog()["qt"]
    archive = c.ROOT / ".cache/sources/qt.tar.xz"
    download(pin["url"], pin["sha256"], archive)
    root = c.ROOT / ".cache/qt"
    source = root / pin["directory"]
    if not source.exists():
        root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as tar:
            # Reject symlinks and traversal even on Python 3.11.
            for member in tar.getmembers():
                dest = (root / member.name).resolve()
                if not dest.is_relative_to(root.resolve()) or member.issym() or member.islnk() or member.isdev():
                    raise c.Failure("unsafe Qt archive entry")
            if hasattr(tarfile, "data_filter"):
                tar.extractall(root, filter="data")
            else:
                tar.extractall(root)  # entries were checked above, including links
    family, cc, cxx = c.compiler(cfg, "debug")
    c.run(["cmake", "-S", source, "-B", root / "build", "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_C_COMPILER={cc}", f"-DCMAKE_CXX_COMPILER={cxx}", f"-DCMAKE_INSTALL_PREFIX={root / 'install'}", "-DQT_BUILD_TESTS=OFF", "-DQT_BUILD_EXAMPLES=OFF", "-DBUILD_SHARED_LIBS=ON"])
    c.run(["cmake", "--build", root / "build", "--parallel", os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL", "2")])
    c.run(["cmake", "--install", root / "build"])

def setup(cfg):
    verify_lock(cfg)
    prepare_qt(cfg)
    if cfg["dependencies"] == "native":
        for name, pin in c.catalog()["packages"].items():
            archive = c.ROOT / ".cache/sources" / f"{name}.tar.gz"
            download(pin["url"], pin["sha256"], archive)
            if cfg["build_system"] == "meson":
                cache = c.ROOT / "subprojects/packagecache"
                cache.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(archive, cache / archive.name)
    for variant in c.variants(cfg):
        directory = c.build_dir(cfg, variant)
        directory.mkdir(parents=True, exist_ok=True)
        if cfg["dependencies"] == "conan":
            profile = conan_profile(cfg, variant)
            c.run(["conan", "install", ".", "-pr:h", profile, "-pr:b", profile, "-s:b", "build_type=Release", "--lockfile=conan.lock", "--build=missing", f"-of={directory / 'conan'}"])
        if cfg["dependencies"] == "vcpkg":
            vcpkg_install(cfg, variant)
        from .build import configure
        configure(cfg, variant)
        c.write_json(directory / "setup.json", {"fingerprint": c.fingerprint(cfg), "qt_root": qt_prefix(cfg)})

def ready(cfg, variant):
    verify_lock(cfg)
    directory = c.build_dir(cfg, variant)
    path = directory / "setup.json"
    if not path.is_file() or json.loads(path.read_text()).get("fingerprint") != c.fingerprint(cfg):
        raise c.Failure(f"{variant} is not set up for these settings; run scripts/project.py setup")
    if cfg["dependencies"] == "native":
        for name, pin in c.catalog()["packages"].items():
            path = c.ROOT / ".cache/sources" / f"{name}.tar.gz"
            if not path.is_file() or c.digest(path) != pin["sha256"]:
                raise c.Failure(f"native dependency {name} is missing or corrupt")
