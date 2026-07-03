"""Tests for single-attempt execution mixin helpers."""
from __future__ import annotations

from platform_core.orchestration.execute_attempt_mixin import OrchestratorExecuteAttemptMixin


class _Lock:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return None


class _State:
    def __init__(self) -> None:
        self.meta = {"work_profile": "standard", "run_intent_policy": {"mode": "watch"}}
        self.updated = {}

    def updateSubtask(self, sid, **fields):
        self.updated[sid] = fields


def test_record_attempt_session_records_routed_metadata():
    host = OrchestratorExecuteAttemptMixin()
    host._state_lock = _Lock()
    state = _State()
    subtask = {"session": {"existing": True}}

    host._recordAttemptSession(state, subtask, {"effort_level": "low", "skills_to_invoke": ["x"]}, "st-1", 2)

    session = state.updated["st-1"]["session"]
    assert session["existing"] is True
    assert session["effort"] == "low"
    assert session["skills"] == ["x"]
    assert session["attempts"] == 2
    assert session["work_profile"] == "standard"
