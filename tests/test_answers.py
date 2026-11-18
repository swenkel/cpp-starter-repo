import itertools
import json
from pathlib import Path
import tempfile
import unittest
from starter.answers import parse, load, AnswerError
from starter.payload.schema import resolve, checks, FAMILIES
from starter.questions import ask

class AnswersTest(unittest.TestCase):
    def test_presets_and_overrides(self):
        for preset, enabled, coverage in (("strict", "yes", "90"), ("balanced", "yes", "0"), ("minimal", "no", "0")):
            with self.subTest(preset=preset):
                a = parse({"name": "example", "quality": preset})
                self.assertEqual(a.clang_tidy, enabled)
                self.assertEqual(a.coverage, coverage)
                self.assertEqual(resolve(a.values), a.values)
        a = parse({"name": "example", "quality": "minimal", "clang_tidy": "yes", "guidelines": ["cert"], "coverage": "100"})
        self.assertEqual(a.coverage, "100")
        self.assertEqual(a.guidelines, ["cert"])

    def test_every_primary_combination(self):
        for profile, backend, provider, test in itertools.product(("cli", "library", "header-only", "http", "numerical", "qt"), ("cmake", "meson"), ("native", "conan", "vcpkg"), ("catch2", "gtest")):
            raw = dict(name="demo", profile=profile, build_system=backend, dependencies=provider, test_runner=test)
            if profile == "qt": raw["qt_source"] = "installed"
            self.assertEqual(resolve(parse(raw).values), parse(raw).values)

    def test_invalid_inputs(self):
        invalid = [{}, {"name": "../escape"}, {"name": "std"}, {"name": "class"}, {"name": "A"}, {"name": "x", "unknown": "yes"}, {"name": "x", "quality": "custom"}, {"name": "x", "coverage": 90}, {"name": "x", "guidelines": "core"}, {"name": "x", "guidelines": ["misra"]}, {"name": "x", "tidy_add": ["bugprone-*"]}, {"name": "x", "tidy_options": {"Bad": 1}}, {"name": "x", "clang_tidy": "no", "guidelines": ["core"]}]
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(AnswerError): parse(raw)

    def test_qt_conditional_choices(self):
        for raw in ({"profile": "qt"}, {"profile": "qt", "qt_source": "provider"}, {"profile": "qt", "qt_source": "image"}, {"base_image": "custom"}, {"environment": "local", "container_image": "image:tag"}):
            with self.subTest(raw=raw), self.assertRaises(AnswerError): parse({"name": "x", **raw})
        a = parse({"name": "x", "profile": "qt", "qt_source": "image", "base_image": "custom", "container_image": "registry.example/qt@sha256:abc"})
        self.assertEqual(a.qt_source, "image")

    def test_exact_rule_removal_wins(self):
        rule = FAMILIES["core"][0]
        a = parse({"name": "x", "guidelines": ["core"], "tidy_add": [rule], "tidy_remove": [rule]})
        self.assertNotIn(rule, checks(a.values))

    def test_json_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "a.json"
            p.write_text(json.dumps({"name": "demo", "guidelines": ["core"]}))
            self.assertEqual(parse(load(p)).guidelines, ["core"])

    def test_interactive_defaults(self):
        replies = iter(["demo"] + [""] * 30)
        a = parse(ask(lambda prompt: next(replies), lambda message: None))
        self.assertEqual(a.quality, "strict")
        self.assertEqual(a.profile, "cli")
