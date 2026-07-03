"""Unit tests for TaskState.listRecent."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from state.task import TaskState


class TestListRecent(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def _w(self, name, tid, status, started, subs):
        (self.dir / name).write_text(json.dumps({
            "task_id": tid,
            "meta": {"status": status, "goal_raw": "goal " + tid, "started_at": started},
            "plan": {"subtasks": subs}}), encoding="utf-8")

    def test_load_safe_returns_none_on_corrupt_or_missing(self):
        good_id = "33333333-3333-4333-8333-333333333333"
        bad_id = "44444444-4444-4444-8444-444444444444"
        missing_id = "55555555-5555-4555-8555-555555555555"
        (self.dir / f"{good_id}.json").write_text(
            json.dumps({"task_id": good_id, "meta": {}, "plan": {"subtasks": []}}), encoding="utf-8")
        (self.dir / f"{bad_id}.json").write_text("{broken", encoding="utf-8")
        with mock.patch.object(config, "STATE_DIR", self.dir):
            self.assertIsNotNone(TaskState.loadSafe(good_id))
            self.assertIsNone(TaskState.loadSafe(bad_id))
            self.assertIsNone(TaskState.loadSafe(missing_id))

    def test_load_rejects_path_traversal_task_id(self):
        # BUG-003: a non-UUID task_id (e.g. path-traversal payload) must be rejected before any
        # path is constructed under STATE_DIR, not silently resolved outside it.
        with mock.patch.object(config, "STATE_DIR", self.dir):
            with self.assertRaises(ValueError):
                TaskState.load("../../.env")

    def test_iter_stored_skips_corrupt(self):
        self._w("ok.json", "ok1", "done", "2026-06-22T08:00:00+00:00", [])
        (self.dir / "broken.json").write_text("{not json", encoding="utf-8")
        with mock.patch.object(config, "STATE_DIR", self.dir):
            ids = sorted(d.get("task_id") for _f, d in TaskState.iterStored())
        self.assertEqual(ids, ["ok1"])   # the corrupt file is silently skipped

    def test_sorted_desc_with_progress(self):
        self._w("a.json", "aaa", "done", "2026-06-22T08:00:00+00:00", [{"status": "done"}])
        self._w("b.json", "bbb", "executing", "2026-06-22T10:00:00+00:00",
                 [{"status": "done"}, {"status": "pending"}])
        with mock.patch.object(config, "STATE_DIR", self.dir):
            rec = TaskState.listRecent(5)
        self.assertEqual(len(rec), 2)
        self.assertEqual(rec[0]["task_id"], "bbb")          # most recent first
        self.assertEqual((rec[0]["done"], rec[0]["total"]), (1, 2))
        self.assertEqual(rec[0]["status"], "executing")

    def test_limit(self):
        for i in range(5):
            self._w(f"{i}.json", f"t{i}", "done", f"2026-06-22T0{i}:00:00+00:00", [])
        with mock.patch.object(config, "STATE_DIR", self.dir):
            self.assertEqual(len(TaskState.listRecent(3)), 3)


if __name__ == "__main__":
    unittest.main()
