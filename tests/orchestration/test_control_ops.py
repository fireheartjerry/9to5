"""Tests for queued ControlBus plan op application."""
from __future__ import annotations

from types import SimpleNamespace

from platform_core.orchestration.control_ops import applyOp


class _State:
    def __init__(self) -> None:
        self.subtasks = [{"subtask_id": "st-1", "title": "old", "status": "pending"}]
        self.meta = {}
        self.saved = False
        self.intents = []

    def getSubtask(self, sid):
        return next((s for s in self.subtasks if s["subtask_id"] == sid), None)

    def updateSubtask(self, sid, **fields):
        self.getSubtask(sid).update(fields)

    def addSubtask(self, title, description):
        subtask = {"subtask_id": "st-2", "title": title, "description": description, "status": "pending"}
        self.subtasks.append(subtask)
        return subtask

    def addIntent(self, text):
        self.intents.append(text)

    def save(self):
        self.saved = True


def test_apply_skip_and_add_ops():
    state = _State()
    dashboard = SimpleNamespace(events=[], event=lambda msg: dashboard.events.append(msg))

    applyOp(state, {"op": "skip", "subtask_id": "st-1"}, dashboard)
    applyOp(state, {"op": "add", "title": "new", "description": "desc"}, dashboard)

    assert state.subtasks[0]["status"] == "removed"
    assert state.subtasks[1]["title"] == "new"
    assert dashboard.events == ["skipped st-1", "added st-2"]
