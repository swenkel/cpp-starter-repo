"""Remove the starter from its own directory.

Deletion is limited to the fixed names below, directly inside the starter
root. Nothing is globbed and no path is derived from user input.
"""

import shutil
from pathlib import Path

SENTINEL: str = "starter/versions.py"
STAGING: str = ".starter-staging"
STARTER_PATHS: tuple[str, ...] = (
    ".github",
    ".starter-manifest.json",
    ".dockerignore",
    ".git",
    ".gitignore",
    "LICENSE",
    "README.md",
    "bootstrap.py",
    "starter",
    "tests",
)
CACHE_PATHS: tuple[str, ...] = (
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
)


class StarterError(RuntimeError):
    """The starter refuses to continue; nothing further is changed."""


def preflight(root: Path) -> None:
    """Verify that ``root`` is an untouched starter checkout."""
    if root.is_symlink() or not root.is_dir():
        raise StarterError(f"{root} is not a real directory")
    resolved: Path = root.resolve()
    if resolved in {Path(resolved.anchor), Path.home().resolve()}:
        raise StarterError(f"refusing to work in {resolved}")
    if not (root / SENTINEL).is_file():
        raise StarterError(f"{root} is not a starter checkout")
    if (root / STAGING).exists():
        raise StarterError(
            f"{STAGING} exists from an earlier run; inspect and remove it"
        )
    known: set[str] = set(STARTER_PATHS) | set(CACHE_PATHS)
    unexpected: list[str] = sorted(
        entry.name for entry in root.iterdir() if entry.name not in known
    )
    if unexpected:
        raise StarterError(
            "files that do not belong to the starter would be mixed into "
            f"the new project; move them away first: {', '.join(unexpected)}"
        )

    from starter.manifest import verify

    verify(root)


def remove_entry(root: Path, name: str) -> None:
    """Delete one direct child of ``root`` without following symlinks."""
    path: Path = root / name
    if path.parent != root or name in {"", ".", ".."}:
        raise StarterError(f"refusing to delete {name!r}")
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def remove_starter(root: Path) -> None:
    """Delete the starter's own files, its caches and its git history."""
    for name in STARTER_PATHS + CACHE_PATHS:
        remove_entry(root, name)
