"""Unit tests for run-metrics aggregation."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from notifications import metrics


def _task(status, subs):
    return {"meta": {"status": status, "started_at": "2026-06-22T09:00:00+00:00"},
            "plan": {"subtasks": subs}}


class TestMetrics(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def _write(self, name, obj):
        (self.dir / name).write_text(json.dumps(obj), encoding="utf-8")

    def test_aggregation(self):
        self._write("a.json", _task("done", [
            {"status": "done", "verify_result": {"passed": True},
             "completed_at": "2026-06-22T09:10:00+00:00"}]))
        self._write("b.json", _task("failed", [
            {"status": "failed", "verify_result": {"passed": False},
             "completed_at": "2026-06-22T09:05:00+00:00"}]))
        self._write("c.json", _task("executing", [{"status": "pending"}]))
        with mock.patch.object(config, "STATE_DIR", self.dir):
            m = metrics.compute()
        self.assertEqual(m["total_runs"], 3)
        self.assertEqual(m["terminal_runs"], 2)
        self.assertEqual(m["success_runs"], 1)
        self.assertEqual(m["success_rate"], 0.5)
        self.assertEqual(m["subtasks_total"], 3)
        self.assertEqual(m["subtasks_passed"], 1)
        self.assertIsNotNone(m["avg_duration_seconds"])

    def test_empty(self):
        with mock.patch.object(config, "STATE_DIR", self.dir):
            m = metrics.compute()
        self.assertEqual(m["total_runs"], 0)
        self.assertIsNone(m["success_rate"])
        self.assertIsNone(m["avg_duration_seconds"])
