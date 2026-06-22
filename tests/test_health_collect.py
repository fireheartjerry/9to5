"""Unit tests for health.collectHealth (structured results)."""
import unittest
from unittest import mock

import health


class TestCollectHealth(unittest.TestCase):
    def test_shape(self):
        fake = [("x", lambda: (True, "ok", "")), ("y", lambda: (False, "bad", "fixit"))]
        with mock.patch.object(health, "CHECKS", fake):
            checks = health.collectHealth()
        self.assertEqual(len(checks), 2)
        for c in checks:
            self.assertEqual(set(c), {"name", "ok", "detail", "fix"})
            self.assertIsInstance(c["ok"], bool)
        self.assertFalse(checks[1]["ok"])
        self.assertEqual(checks[1]["fix"], "fixit")

    def test_check_exception_captured(self):
        def boom():
            raise RuntimeError("nope")
        with mock.patch.object(health, "CHECKS", [("z", boom)]):
            checks = health.collectHealth()
        self.assertFalse(checks[0]["ok"])
        self.assertIn("errored", checks[0]["detail"])


if __name__ == "__main__":
    unittest.main()
