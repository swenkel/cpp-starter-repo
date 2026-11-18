"""End-to-end tests: generation, self-removal and their safety checks."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from starter import answers, cleanup, plan
from starter.cleanup import StarterError
from tests.support import DEFAULTS

REPOSITORY: Path = Path(__file__).resolve().parents[1]
STARTER_FILES: tuple[str, ...] = (
    ".github",
    ".starter-manifest.json",
    ".dockerignore",
    ".gitignore",
    "LICENSE",
    "README.md",
    "bootstrap.py",
    "starter",
    "tests",
)


def tree(root: Path) -> set[str]:
    """Return all files below ``root`` except git internals."""
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


class StarterCopy(unittest.TestCase):
    """Base class giving each test a disposable copy of the starter."""

    def setUp(self) -> None:
        """Copy the starter and give it a fake git history."""
        self.sandbox: Path = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.root: Path = self.sandbox / "checkout"
        self.root.mkdir()
        ignore = shutil.ignore_patterns("__pycache__")
        for name in STARTER_FILES:
            source: Path = REPOSITORY / name
            if source.is_dir():
                shutil.copytree(source, self.root / name, ignore=ignore)
            elif source.is_file():
                shutil.copy2(source, self.root / name)
        if shutil.which("git") is None:
            self.skipTest("git is required for checkout fixtures")
        for args in (["init", "-q"], ["add", "."],
                     ["-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                      "commit", "-qm", "starter history"]):
            subprocess.run(["git", *args], cwd=self.root, check=True)

    def bootstrap(
        self, raw: dict[str, str], *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        """Run the copied starter with an answers file outside it."""
        answers_file: Path = self.sandbox / "answers.json"
        answers_file.write_text(json.dumps(raw), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(self.root / "bootstrap.py"),
                "--answers",
                str(answers_file),
                *arguments,
            ],
            capture_output=True,
            text=True,
            check=False,
            env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"},
        )

    def expected(self, raw: dict[str, str]) -> set[str]:
        """Return the paths a project with these answers consists of."""
        parsed: answers.Answers = answers.parse(raw)
        paths: set[str] = {file.path for file in plan.build(parsed)}
        if parsed.guard == "seal":
            paths.add("scripts/gates.sha256")
        return paths


class SelfRemovalTest(StarterCopy):
    """The starter replaces itself with exactly the planned project."""

    def test_only_the_project_remains(self) -> None:
        """No starter file or git history survives generation."""
        for changes in (
            {"git_init": "no"},
            {
                "git_init": "no",
                "profile": "header-only",
                "environment": "local",
                "guard": "policy",
                "ci": "none",
                "test_runner": "gtest",
            },
        ):
            with self.subTest(changes=changes):
                self.setUp()
                raw: dict[str, str] = DEFAULTS | changes
                finished: subprocess.CompletedProcess[str] = self.bootstrap(
                    raw
                )
                self.assertEqual(finished.returncode, 0, finished.stderr)
                self.assertEqual(tree(self.root), self.expected(raw))
                self.assertFalse((self.root / ".git").exists())
                self.assertFalse((self.root / "bootstrap.py").exists())
                self.assertFalse((self.root / "starter").exists())
                self.assertFalse((self.root / cleanup.STAGING).exists())
                self.assertEqual(
                    {path.name for path in self.sandbox.iterdir()},
                    {"checkout", "answers.json"},
                )

    def test_hook_is_executable_and_shell_syntax_is_valid(self) -> None:
        """Generated shell entry points are runnable."""
        self.assertEqual(
            self.bootstrap(DEFAULTS | {"git_init": "no"}).returncode, 0
        )
        shell: str | None = shutil.which("sh")
        for name in (".githooks/pre-commit", "scripts/check.sh"):
            path: Path = self.root / name
            self.assertTrue(os.access(path, os.X_OK), name)
            if shell is not None:
                subprocess.run([shell, "-n", str(path)], check=True)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_git_init_creates_fresh_history_and_enables_hook(self) -> None:
        """The new repository has no commits and uses the tracked hook."""
        self.assertEqual(self.bootstrap(DEFAULTS).returncode, 0)
        head: str = (self.root / ".git" / "HEAD").read_text()
        self.assertNotIn("starter history", head)
        config: str = (self.root / ".git" / "config").read_text()
        self.assertIn("hooksPath = .githooks", config)
        self.assertFalse((self.root / ".git" / "index").exists())


class RefusalTest(StarterCopy):
    """Unsafe situations stop the starter before it changes anything."""

    def test_foreign_files_stop_generation(self) -> None:
        """User files are never deleted or mixed into the project."""
        (self.root / "notes.txt").write_text("mine")
        before: set[str] = tree(self.root)
        finished: subprocess.CompletedProcess[str] = self.bootstrap(DEFAULTS)
        self.assertEqual(finished.returncode, 2)
        self.assertIn("notes.txt", finished.stderr)
        self.assertEqual(tree(self.root), before)
        self.assertTrue((self.root / ".git" / "HEAD").is_file())

    def test_invalid_answers_stop_generation(self) -> None:
        """Validation happens before any filesystem change."""
        before: set[str] = tree(self.root)
        finished: subprocess.CompletedProcess[str] = self.bootstrap(
            DEFAULTS | {"cpp_standard": "11"}
        )
        self.assertEqual(finished.returncode, 2)
        self.assertEqual(tree(self.root), before)

    def test_dry_run_writes_nothing(self) -> None:
        """A dry run lists the plan and leaves the starter untouched."""
        before: set[str] = tree(self.root)
        finished: subprocess.CompletedProcess[str] = self.bootstrap(
            DEFAULTS, "--dry-run"
        )
        self.assertEqual(finished.returncode, 0)
        self.assertIn("scripts/project.py", finished.stdout)
        self.assertEqual(tree(self.root), before)

    def test_output_keeps_the_starter(self) -> None:
        """With --output the project goes elsewhere."""
        before: set[str] = tree(self.root)
        target: Path = self.sandbox / "project"
        raw: dict[str, str] = DEFAULTS | {"git_init": "no"}
        finished: subprocess.CompletedProcess[str] = self.bootstrap(
            raw, "--output", str(target)
        )
        self.assertEqual(finished.returncode, 0, finished.stderr)
        self.assertEqual(tree(target), self.expected(raw))
        self.assertEqual(tree(self.root), before)

    def test_output_must_be_empty(self) -> None:
        """Existing files are never overwritten."""
        target: Path = self.sandbox / "project"
        target.mkdir()
        (target / "keep.txt").write_text("mine")
        finished: subprocess.CompletedProcess[str] = self.bootstrap(
            DEFAULTS, "--output", str(target)
        )
        self.assertEqual(finished.returncode, 2)
        self.assertEqual(tree(target), {"keep.txt"})

    def test_preflight_rejects_unsafe_roots(self) -> None:
        """Symlinks, non-starters and leftovers are refused."""
        link: Path = self.sandbox / "link"
        link.symlink_to(self.root, target_is_directory=True)
        empty: Path = self.sandbox / "empty"
        empty.mkdir()
        for root in (link, empty, Path.home(), Path("/")):
            with self.subTest(root=root), self.assertRaises(StarterError):
                cleanup.preflight(root)
        (self.root / cleanup.STAGING).mkdir()
        with self.assertRaisesRegex(StarterError, "earlier run"):
            cleanup.preflight(self.root)

    def test_remove_entry_only_deletes_direct_children(self) -> None:
        """Deletion cannot escape the root or follow a symlink."""
        outside: Path = self.sandbox / "outside"
        outside.mkdir()
        (outside / "data.txt").write_text("keep")
        for name in ("../outside", "starter/payload", ".", ""):
            with self.subTest(name=name), self.assertRaises(StarterError):
                cleanup.remove_entry(self.root, name)
        shutil.rmtree(self.root / "tests")
        (self.root / "tests").symlink_to(outside, target_is_directory=True)
        cleanup.remove_entry(self.root, "tests")
        self.assertFalse((self.root / "tests").exists())
        self.assertEqual((outside / "data.txt").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
