"""Stage, validate, and safely apply a fully rendered project."""
import json
from pathlib import Path
import shutil
import subprocess
import tomllib
from starter import cleanup
from starter.payload.gates import seal_text
from starter.payload.schema import resolve

def write_tree(target, files, answers):
    target = Path(target)
    if target.is_symlink():
        raise cleanup.StarterError("output must not be a symlink")
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise cleanup.StarterError(f"{target} is not empty")
    for file in files:
        path = target / file.path
        if Path(file.path).is_absolute() or ".." in Path(file.path).parts:
            raise cleanup.StarterError("unsafe planned file path")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(file.content)
        path.chmod(file.mode)
    resolve(tomllib.loads((target / "gates.toml").read_text()))
    json.loads((target / ".clang-tidy").read_text())
    if answers.guard == "seal":
        (target / "scripts/gates.sha256").write_text(seal_text(target))

def generate(root, files, answers, output=None):
    if output is not None:
        output = Path(output).absolute()
        if output.resolve() == root.resolve() or output.resolve().is_relative_to(root.resolve()):
            raise cleanup.StarterError("--output must be outside the starter")
        write_tree(output, files, answers)
        return output
    cleanup.preflight(root)
    staging = root / cleanup.STAGING
    write_tree(staging, files, answers)
    try:
        cleanup.remove_starter(root)
        for entry in sorted(staging.iterdir()):
            entry.replace(root / entry.name)
        staging.rmdir()
    except OSError as error:
        raise cleanup.StarterError(f"replacement interrupted: {error}; staged project remains in {staging}") from error
    return root

def init_git(target):
    if not shutil.which("git"):
        return "Git unavailable; run git init and git config core.hooksPath .githooks manually"
    for args in (("init", "--quiet"), ("config", "core.hooksPath", ".githooks")):
        subprocess.run(["git", *args], cwd=target, check=True)
    return "Initialized a fresh repository with the pre-commit hook; no commit created."
