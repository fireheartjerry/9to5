"""The structured per-run JSONL trace log (tracing.py)."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import platform_core.core.tracing as tracing


class TestTracing(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.patch = mock.patch.object(tracing, "RUNS_ROOT", self.dir)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_emit_and_read_roundtrip(self):
        tracing.emit("run_abc", "verification_failed", subtask_id="st-004",
                     cmd="pytest -q", exit_code=1, next_action="retry_with_failure_context")
        events = tracing.readEvents("run_abc")
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e["event"], "verification_failed")
        self.assertEqual(e["subtask_id"], "st-004")
        self.assertEqual(e["exit_code"], 1)
        self.assertEqual(e["run_id"], "run_abc")
        self.assertIn("ts", e)

    def test_appends_in_order(self):
        tracing.emit("r", "a")
        tracing.emit("r", "b")
        self.assertEqual([e["event"] for e in tracing.readEvents("r")], ["a", "b"])

    def test_read_missing_run_is_empty(self):
        self.assertEqual(tracing.readEvents("does_not_exist"), [])

    def test_corrupt_line_is_skipped_not_fatal(self):
        d = tracing.runDir("r2")
        d.mkdir(parents=True, exist_ok=True)
        (d / "events.jsonl").write_text('{"event": "ok"}\nNOT JSON\n', encoding="utf-8")
        events = tracing.readEvents("r2")
        self.assertEqual([e["event"] for e in events], ["ok"])

    def test_emit_never_raises_on_unwritable_root(self):
        # A tracing failure must never propagate into a run.
        with mock.patch.object(tracing, "runDir", side_effect=OSError("boom")):
            tracing.emit("r", "x")  # must not raise

    def test_recent_run_ids(self):
        tracing.emit("run_one", "a")
        tracing.emit("run_two", "b")
        self.assertEqual(set(tracing.recentRunIds()), {"run_one", "run_two"})
