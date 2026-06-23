"""Unit tests for Orchestrator._applyReplan -- it must never raise on a malformed
brain decision, because it runs AFTER a subtask is marked done and a crash here
would flip that completed subtask to failed via the caller's exception handler."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from orchestrator import Orchestrator
from state.task import TaskState


class TestApplyReplan(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._patch = mock.patch.object(config, "STATE_DIR", self.dir)
        self._patch.start()
        self.state = TaskState.create("goal", 1.0)
        self.state.addSubtask("a", "da")   # st-001 (pending)
        self.orch = Orchestrator()
        self.orch.obs = mock.Mock()        # no Obsidian network/disk in the test

    def tearDown(self):
        self._patch.stop()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def _count(self):
        return sum(1 for s in self.state.subtasks if s["status"] != "removed")

    def test_valid_add_and_remove(self):
        self.orch._applyReplan(self.state, {
            "action": "mutate",
            "add": [{"title": "b", "description": "db"}],
            "remove": ["st-001"],
            "reason": "ok"})
        self.assertEqual(self.state.getSubtask("st-001")["status"], "removed")
        self.assertTrue(any(s["title"] == "b" for s in self.state.subtasks))

    def test_add_not_a_list_does_not_raise(self):
        before = self._count()
        self.orch._applyReplan(self.state, {"add": "rm -rf", "remove": None, "reason": "x"})
        self.assertEqual(self._count(), before)   # nothing added, no crash

    def test_add_items_wrong_type_skipped(self):
        before = self._count()
        self.orch._applyReplan(self.state, {"add": ["just a string", 42, None], "reason": "x"})
        self.assertEqual(self._count(), before)

    def test_remove_not_a_list_does_not_raise(self):
        self.orch._applyReplan(self.state, {"remove": "st-001", "reason": "x"})
        # 'st-001' as a string is iterated as chars only if we let it; we must NOT, so it stays pending
        self.assertEqual(self.state.getSubtask("st-001")["status"], "pending")

    def test_empty_decision_is_noop(self):
        before = self._count()
        self.orch._applyReplan(self.state, {})
        self.assertEqual(self._count(), before)


if __name__ == "__main__":
    unittest.main()
