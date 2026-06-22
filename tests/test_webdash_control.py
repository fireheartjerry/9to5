"""Unit tests for webdash._applyControl -- bus mutations + gate validation."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from control import ControlBus
from notifications import webdash


class TestApplyControl(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._patch = mock.patch.object(config, "CONTROL_DIR", self.dir)
        self._patch.start()
        self.tid = "task-web"

    def tearDown(self):
        self._patch.stop()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_abort_pause_resume(self):
        self.assertTrue(webdash._applyControl(self.tid, "abort", None)["ok"])
        self.assertTrue(ControlBus(self.tid).isAbort())
        webdash._applyControl(self.tid, "pause", None)
        self.assertTrue(ControlBus(self.tid).isPaused())
        webdash._applyControl(self.tid, "resume", None)
        self.assertFalse(ControlBus(self.tid).isPaused())

    def test_approve_valid_gate(self):
        bus = ControlBus(self.tid)
        bus.setPendingGate("plan")
        res = webdash._applyControl(self.tid, "approve", None)
        self.assertTrue(res["ok"])
        self.assertEqual(res["gate"], "plan")
        self.assertEqual(ControlBus(self.tid).getDecision("plan"), "approve")

    def test_approve_unknown_gate_is_rejected(self):
        res = webdash._applyControl(self.tid, "approve", "not-a-gate")
        self.assertFalse(res["ok"])
        # no stray decision key was written
        self.assertNotIn("not-a-gate", ControlBus(self.tid).load()["decisions"])

    def test_approve_without_pending_gate(self):
        res = webdash._applyControl(self.tid, "approve", None)
        self.assertFalse(res["ok"])

    def test_skip_queues_op(self):
        self.assertTrue(webdash._applyControl(self.tid, "skip", "st-002")["ok"])
        self.assertEqual(ControlBus(self.tid).drainOps(),
                         [{"op": "skip", "subtask_id": "st-002"}])

    def test_unknown_action_reports_error(self):
        res = webdash._applyControl(self.tid, "frobnicate", None)
        self.assertFalse(res["ok"])
        self.assertIn("unknown", res["error"])

    def test_incomplete_skip_reports_error(self):
        res = webdash._applyControl(self.tid, "skip", None)
        self.assertFalse(res["ok"])


if __name__ == "__main__":
    unittest.main()
