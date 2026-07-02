"""Unit tests for the file-backed audit log."""
import pathlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Allow `python tests/notifications/test_audit.py` from any working directory.
_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from notifications import audit


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "audit.jsonl"

    def tearDown(self):
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_record_and_recent(self):
        with mock.patch.object(config, "AUDIT_LOG_PATH", self.path):
            audit.record(777, "abort", "task-1")
            audit.record(777, "pause", "task-1", "button")
            entries = audit.recent(10)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[-1]["action"], "pause")
        self.assertEqual(entries[-1]["detail"], "button")
        self.assertEqual(entries[0]["user_id"], "777")

    def test_recent_empty_when_no_file(self):
        with mock.patch.object(config, "AUDIT_LOG_PATH", self.dir / "nope.jsonl"):
            self.assertEqual(audit.recent(), [])

    def test_rotation(self):
        with mock.patch.object(config, "AUDIT_LOG_PATH", self.path), \
                mock.patch.object(config, "AUDIT_MAX_BYTES", 50):
            for i in range(30):
                audit.record(1, f"act{i}", "t")
            self.assertTrue((self.dir / "audit.jsonl.1").exists())
            self.assertTrue(audit.recent(5))   # still works after rotation
