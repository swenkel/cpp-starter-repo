"""Process, configuration, and filesystem helpers for generated projects."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tomllib
from .schema import resolve, ConfigError

ROOT = Path(__file__).resolve().parents[2]

class Failure(RuntimeError):
    pass

def run(args, *, cwd=None, env=None, capture=False):
    args = [str(x) for x in args]
    print("+ " + " ".join(args), flush=True)
    try:
        p = subprocess.run(args, cwd=cwd or ROOT, env=env or os.environ.copy(),
                           text=True, capture_output=capture, check=False)
    except OSError as error:
        raise Failure(f"cannot run {args[0]}: {error}") from error
    if p.returncode:
        if capture:
            print(p.stdout, end="")
            print(p.stderr, end="")
        raise Failure(f"{args[0]} exited {p.returncode}")
    return p.stdout if capture else ""

def load():
    raw = tomllib.loads((ROOT / "gates.toml").read_text())
    cfg = resolve(raw)
    # The shipped config is complete, so omissions cannot weaken a preset.
    if set(raw) != set(cfg):
        raise ConfigError("gates.toml is incomplete; restore missing settings")
    return cfg

def catalog():
    return json.loads((ROOT / "dependencies.json").read_text())

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)

def executable(name):
    found = shutil.which(name)
    if found is None:
        raise Failure(f"missing {name}; follow README tool installation instructions")
    return found

def llvm(name):
    major = catalog()["tools"]["llvm_major"]
    return shutil.which(f"{name}-{major}") or executable(name)

def compiler(cfg, variant):
    if platform.system() not in {"Linux", "Darwin"}:
        raise Failure("only Linux and macOS are supported")
    family = "clang" if platform.system() == "Darwin" or variant == "analysis" else cfg["compiler"]
    return (family, llvm("clang"), llvm("clang++")) if family == "clang" else (family, executable("gcc"), executable("g++"))

def build_dir(cfg, variant):
    family = compiler(cfg, variant)[0]
    return ROOT / "build" / f"{cfg['build_system']}-{cfg['dependencies']}-{family}-{variant}"

def machine_triplet():
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
    system = {"Linux": "linux", "Darwin": "osx"}.get(platform.system())
    if not arch or not system:
        raise Failure("unsupported native architecture/platform")
    return f"{arch}-{system}"

def version_at_least(binary, minimum):
    out = run([binary, "--version"], capture=True)
    match = re.search(r"\b(\d+)\.(\d+)(?:\.(\d+))?", out)
    expected = tuple(int(x) for x in minimum.split("."))
    if not match or tuple(int(x or 0) for x in match.groups())[:len(expected)] < expected:
        raise Failure(f"{binary} requires >= {minimum}")
    return tuple(int(x or 0) for x in match.groups())

def variants(cfg):
    result = ["debug"]
    if cfg["clang_tidy"] == "yes":
        result.append("analysis")
    if cfg["sanitizers"] != "none":
        result.append("sanitizer")
    if cfg["coverage"] != "0":
        result.append("coverage")
    return result

def fingerprint(cfg):
    # Compiler/OS paths belong to build state, not portable locks.
    return hashlib.sha256(json.dumps({"config": cfg, "catalog": catalog()}, sort_keys=True).encode()).hexdigest()

def source_files():
    extensions = {".h", ".hpp", ".hh", ".hxx", ".ipp", ".tpp", ".inl", ".c", ".cc", ".cpp", ".cxx"}
    return sorted(p for directory in ("src", "include", "tests") for p in (ROOT / directory).rglob("*") if p.suffix in extensions and p.is_file())
