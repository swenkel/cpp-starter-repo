import unittest
from unittest.mock import patch
from starter import images

class ImageTest(unittest.TestCase):
    def test_numeric_comparison(self):
        self.assertEqual(images.newest(r"(\d+)", ["9", "13", "latest", "12"]), "13")

    def test_every_pin_matches(self):
        for pin in images.pins():
            self.assertEqual(images.newest(pin.pattern, [pin.pinned]), pin.pinned)

    def test_unknown_tags_fail(self):
        with self.assertRaises(ValueError): images.newest(r"(\d+)", ["latest"])

    def test_http_rejected(self):
        with self.assertRaises(ValueError): images.fetch("http://example.invalid", "")

    def test_updates_report_failure(self):
        with patch.object(images, "list_tags", side_effect=[["13", "14"], ["26.04"]]):
            self.assertEqual(images.check(), 1)
