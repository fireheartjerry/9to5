"""Tests for run-loop replan helper behavior."""
from __future__ import annotations

from platform_core.orchestration.run_loop_replan_mixin import OrchestratorRunLoopReplanMixin


class _State:
    def __init__(self) -> None:
        self.subtasks = [
            {"subtask_id": "a", "status": "removed"},
            {"subtask_id": "b", "status": "pending", "depends_on": ["a"]},
            {"subtask_id": "c", "status": "done", "depends_on": ["b"]},
            {"subtask_id": "d", "status": "pending", "depends_on": ["c"]},
        ]
        self.notifications = []

    def dependentsOf(self, sid):
        return [s for s in self.subtasks if sid in s.get("depends_on", [])]

    def updateSubtask(self, sid, **fields):
        next(s for s in self.subtasks if s["subtask_id"] == sid).update(fields)

    def addNotification(self, kind, text):
        self.notifications.append((kind, text))


def test_cascade_reset_removes_pending_dependents_through_done_nodes():
    host = OrchestratorRunLoopReplanMixin()
    state = _State()

    host._cascadeResetDependents(state, ["a"])

    by_id = {s["subtask_id"]: s for s in state.subtasks}
    assert by_id["b"]["status"] == "removed"
    assert by_id["c"]["status"] == "done"
    assert by_id["d"]["status"] == "removed"
    assert state.notifications == [
        ("cascade_reset", "b (depended on a)"),
        ("cascade_reset", "d (depended on c)"),
    ]
