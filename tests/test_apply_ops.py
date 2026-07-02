"""Unit tests for Orchestrator._applyOps -- queued !skip/!add/!retry application
and the feedback emitted when a skip cannot be honored."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from orchestrator import Orchestrator
from state.task import TaskState


class _Bus:
    """Minimal ControlBus stand-in: yields its ops once, then drains empty."""
    def __init__(self, ops):
        self._ops = list(ops)

    def drainOps(self):
        ops, self._ops = self._ops, []
        return ops


class _Dash:
    def __init__(self):
        self.events = []

    def event(self, text):
        self.events.append(text)


class TestApplyOps(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._patch = mock.patch.object(config, "STATE_DIR", self.dir)
        self._patch.start()
        self.state = TaskState.create("goal", 1.0)
        self.state.addSubtask("a", "da")   # st-001
        self.state.addSubtask("b", "db")   # st-002
        self.orch = Orchestrator()
        self.dash = _Dash()

    def tearDown(self):
        self._patch.stop()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_skip_pending_removes(self):
        self.orch._applyOps(self.state, _Bus([{"op": "skip", "subtask_id": "st-002"}]), self.dash)
        self.assertEqual(self.state.getSubtask("st-002")["status"], "removed")
        self.assertIn("skipped st-002", self.dash.events)

    def test_skip_in_progress_is_ignored_with_feedback(self):
        self.state.updateSubtask("st-001", status="in_progress")
        self.orch._applyOps(self.state, _Bus([{"op": "skip", "subtask_id": "st-001"}]), self.dash)
        self.assertEqual(self.state.getSubtask("st-001")["status"], "in_progress")
        self.assertTrue(any("skip ignored" in e and "st-001" in e for e in self.dash.events),
                        self.dash.events)

    def test_skip_unknown_id_reports_not_found(self):
        self.orch._applyOps(self.state, _Bus([{"op": "skip", "subtask_id": "st-999"}]), self.dash)
        self.assertTrue(any("not found" in e for e in self.dash.events), self.dash.events)

    def test_add_creates_subtask(self):
        before = len(self.state.subtasks)
        self.orch._applyOps(self.state, _Bus([{"op": "add", "title": "c", "description": "dc"}]), self.dash)
        self.assertEqual(len(self.state.subtasks), before + 1)
        self.assertTrue(any(e.startswith("added ") for e in self.dash.events))

    def test_retry_resets_in_progress_to_pending(self):
        self.state.updateSubtask("st-001", status="in_progress")
        self.orch._applyOps(self.state, _Bus([{"op": "retry"}]), self.dash)
        self.assertEqual(self.state.getSubtask("st-001")["status"], "pending")
