import ast
import itertools
import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from starter.answers import parse
from starter.plan import build
from starter.apply import write_tree
from starter.payload.schema import resolve
from starter.payload.gates import seal_text

class RenderTest(unittest.TestCase):
    def test_matrix_is_well_formed_and_deterministic(self):
        for profile, backend, provider, runner in itertools.product(("cli", "library", "header-only", "http", "numerical", "qt"), ("cmake", "meson"), ("native", "conan", "vcpkg"), ("catch2", "gtest")):
            raw = dict(name="demo", profile=profile, build_system=backend, dependencies=provider, test_runner=runner)
            if profile == "qt": raw["qt_source"] = "installed"
            a = parse(raw)
            with self.subTest(raw=raw):
                files = build(a)
                self.assertEqual(files, build(a))
                data = {f.path: f.content for f in files}
                self.assertEqual(len(data), len(files))
                self.assertEqual(resolve(tomllib.loads(data["gates.toml"])), a.values)
                for name, source in data.items():
                    if name.endswith(".py"): ast.parse(source, filename=name)
                    if name.endswith(".json") or name == ".clang-tidy": json.loads(source)
                self.assertEqual("CMakeLists.txt" in data, backend == "cmake")
                self.assertEqual("meson.build" in data, backend == "meson")
                self.assertEqual("conanfile.py" in data, provider == "conan")
                self.assertEqual("vcpkg.json" in data, provider == "vcpkg")

    def test_seal_covers_enforcement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a = parse({"name": "demo"})
            write_tree(root, build(a), a)
            before = seal_text(root)
            self.assertEqual((root / "scripts/gates.sha256").read_text(), before)
            for name in ("gates.toml", "CMakeLists.txt", ".clang-tidy", "scripts/lib/gates.py", "Dockerfile"):
                path = root / name
                original = path.read_text()
                path.write_text(original + "\n")
                self.assertNotEqual(seal_text(root), before)
                path.write_text(original)
            source = root / "src/core.cpp"
            source.write_text(source.read_text() + "\n")
            self.assertEqual(seal_text(root), before)

    def test_conditional_files(self):
        a = parse({"name": "demo", "environment": "local", "ci": "none", "guard": "policy"})
        names = {f.path for f in build(a)}
        for path in ("Dockerfile", "compose.yaml", ".github/workflows/check.yaml", ".claude/settings.json"):
            self.assertNotIn(path, names)
        a = parse({"name": "demo", "base_image": "custom", "container_image": "registry/qt:1"})
        data = {f.path: f.content for f in build(a)}
        self.assertNotIn("Dockerfile", data)
        self.assertIn("registry/qt:1", data["compose.yaml"])

    def test_provider_qt_is_not_duplicated(self):
        for provider in ("conan", "vcpkg"):
            a = parse(dict(name="demo", profile="qt", dependencies=provider, qt_source="installed"))
            data = {f.path: f.content for f in build(a)}
            source = data.get("conanfile.py", data.get("vcpkg.json"))
            self.assertNotIn("qtbase", source)
            self.assertNotIn("qt/", source)
