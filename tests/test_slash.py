"""Unit tests for pure helpers in notifications/slash.py (no gateway needed)."""
import time
import unittest

from notifications.slash import _fmtUptime


class TestFmtUptime(unittest.TestCase):
    def test_seconds_only(self):
        now = time.time()
        result = _fmtUptime(now - 45)
        self.assertEqual(result, "0m45s")

    def test_minutes_no_hours(self):
        now = time.time()
        result = _fmtUptime(now - 125)
        self.assertEqual(result, "2m05s")

    def test_hours_and_minutes(self):
        now = time.time()
        result = _fmtUptime(now - 3661)
        self.assertEqual(result, "1h01m")

    def test_zero_elapsed(self):
        now = time.time()
        result = _fmtUptime(now + 5)
        self.assertEqual(result, "0m00s")

    def test_exact_one_hour(self):
        now = time.time()
        result = _fmtUptime(now - 3600)
        self.assertEqual(result, "1h00m")

    def test_large_hours(self):
        now = time.time()
        result = _fmtUptime(now - 7 * 3600 + 60)
        self.assertIn("h", result)
