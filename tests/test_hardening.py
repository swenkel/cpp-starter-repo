import json
from pathlib import Path
import shutil
import unittest
from starter import cleanup
from starter.manifest import inventory, MANIFEST
from tests.test_apply import StarterCopy

class SafetyTest(StarterCopy):
    def test_manifest_matches(self):
        self.assertEqual(json.loads((self.root / MANIFEST).read_text()), inventory(self.root))

    def test_archive_replacement(self):
        shutil.rmtree(self.root / ".git")
        self.assertEqual(self.bootstrap({"name": "demo", "git_init": "no"}).returncode, 0)

    def test_changed_and_hidden_files_preserved(self):
        for name in ("starter/versions.py", "tests/private.txt", "tests/__pycache__/notes.txt"):
            with self.subTest(name=name):
                self.setUp()
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("keep")
                with self.assertRaises(cleanup.StarterError): cleanup.preflight(self.root)
                self.assertEqual(path.read_text(), "keep")

    def test_worktree_rejected(self):
        shutil.rmtree(self.root / ".git")
        (self.root / ".git").write_text("gitdir: /elsewhere")
        with self.assertRaises(cleanup.StarterError): cleanup.preflight(self.root)

    def test_foreign_empty_directory_rejected(self):
        (self.root / "tests/private").mkdir()
        with self.assertRaises(cleanup.StarterError): cleanup.preflight(self.root)
