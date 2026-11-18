import json
import configparser
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from starter.payload import common as c, gates, deps, build as builder
from starter.answers import parse
from starter.apply import write_tree
from starter.plan import build

class GateTest(unittest.TestCase):
    def test_suppression_policies(self):
        for text in ("// NOLINT", "// NOLINT(*) -- reason: test", "// cppcheck-suppress *", "// clang-format off", "// GCOVR_EXCL_LINE"):
            self.assertTrue(gates.suppression_problems(text, "none"))
            self.assertTrue(gates.suppression_problems(text, "narrow"))
            self.assertFalse(gates.suppression_problems(text, "unrestricted"))
        for text in ("// NOLINTNEXTLINE(bugprone-branch-clone) -- reason: external contract", "// cppcheck-suppress unusedFunction -- reason: exported API"):
            self.assertFalse(gates.suppression_problems(text, "narrow"))
            self.assertTrue(gates.suppression_problems(text, "none"))

    def test_literals_are_not_comments(self):
        for source in ('const char *s = "// NOLINT";', 'auto s = R"tag(// NOLINT\n/* cppcheck-suppress */)tag";', 'auto s = u8R"(// NOLINT)";', 'char c = \'"\';'):
            self.assertFalse(gates.suppression_problems(source, "none"))
        self.assertTrue(gates.suppression_problems('auto s = R"(safe)"; // NOLINT', "none"))

    def test_pragma_suppression(self):
        self.assertTrue(gates.suppression_problems('#pragma clang diagnostic ignored "-Wextra"', "none"))
        self.assertFalse(gates.suppression_problems('const char *s = "#pragma clang diagnostic ignored";', "none"))

    def test_digit_separators_and_line_splices(self):
        self.assertTrue(gates.suppression_problems("int n = 1'000; // NOLINT", "none"))
        self.assertTrue(gates.suppression_problems("// NOLI\\\nNT", "none"))
        self.assertFalse(gates.suppression_problems("auto c = u8'a';", "none"))

    def test_lock_changes_are_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a = parse(dict(name="demo", quality="minimal", environment="local"))
            write_tree(root, build(a), a)
            with patch.object(c, "ROOT", root):
                with self.assertRaises(c.Failure): deps.verify_lock(a.values)
                deps.lock(a.values)
                deps.verify_lock(a.values)
                p = root / "dependencies.json"
                p.write_text(p.read_text() + "\n")
                with self.assertRaises(c.Failure): deps.verify_lock(a.values)

    def test_seal_survives_guard_downgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a = parse(dict(name="demo"))
            write_tree(root, build(a), a)
            with patch.object(c, "ROOT", root):
                gates.integrity(a.values)
                p = root / "gates.toml"
                p.write_text(p.read_text().replace('guard = "seal"', 'guard = "policy"'))
                with self.assertRaises(c.Failure): gates.integrity(c.load())

    def test_missing_command_is_failure(self):
        with self.assertRaises(c.Failure): c.run(["/nonexistent/cpp-starter-test-tool"])

    def test_managed_provider_rejects_system_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for backend in ("cmake", "meson"):
                cfg = parse(dict(name="demo", dependencies="conan", build_system=backend, test_runner="gtest")).values
                with patch.object(c, "ROOT", root), patch.object(c, "compiler", return_value=("clang", "clang", "clang++")):
                    variant = c.build_dir(cfg, "debug")
                    variant.mkdir(parents=True, exist_ok=True)
                    for location, accepted in (("/usr/lib/cmake/GTest", False), (str(variant / "conan"), True)):
                        (variant / "CMakeCache.txt").write_text(f"GTest_DIR:PATH={location}\n")
                        with patch.object(c, "run", return_value=location), patch.object(builder, "environment", return_value={}):
                            if accepted:
                                builder.verify_provider(cfg, "debug")
                            else:
                                with self.assertRaisesRegex(c.Failure, "outside the selected conan provider"):
                                    builder.verify_provider(cfg, "debug")

    def test_checksum_rejects_cached_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "source.tar.gz"
            p.write_text("corrupt")
            with self.assertRaises(c.Failure): deps.download("https://example.invalid/source", "0" * 64, p)

    def test_conan_gnu_mode_is_scoped_to_managed_qt(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(c, "ROOT", Path(directory)), patch.object(c, "compiler", return_value=("clang", "clang", "clang++")), patch.object(c, "version_at_least", return_value=(21, 1, 8)), patch.dict(os.environ, {"CMAKE_BUILD_PARALLEL_LEVEL": "3"}):
                for standard in ("17", "20", "23"):
                    for extra in ({}, {"profile": "qt", "qt_source": "installed"}, {"profile": "qt", "qt_source": "provider"}):
                        with self.subTest(standard=standard, extra=extra):
                            cfg = parse(dict(name="demo", dependencies="conan", cpp_standard=standard, **extra)).values
                            profile = configparser.ConfigParser(interpolation=None, delimiters=("=",))
                            profile.read(deps.conan_profile(cfg, "debug"))
                            self.assertEqual(profile["settings"]["compiler.cppstd"], standard)
                            expected = "gnu" + standard if extra.get("qt_source") == "provider" else None
                            self.assertEqual(profile["settings"].get("qt/*:compiler.cppstd"), expected)
                            self.assertEqual(profile["conf"]["tools.build:jobs"], "3")

    def test_check_keeps_independent_failures_and_blocks_dependents(self):
        cfg = parse(dict(name="demo", quality="minimal")).values
        with patch.object(gates, "toolchain", side_effect=c.Failure("missing compiler")), patch.object(gates, "integrity"), patch.object(gates, "file_guard"), patch.object(gates, "suppressions", side_effect=c.Failure("forbidden suppression")), patch.object(deps, "verify_lock"), patch.object(gates.build, "build") as compiler:
            self.assertEqual(gates.check(cfg), 1)
            compiler.assert_not_called()
