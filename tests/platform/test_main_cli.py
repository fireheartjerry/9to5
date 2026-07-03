"""Tests for main CLI helper functions."""
from __future__ import annotations

from platform_core.cli import main_cli


def test_mention_shorthand_adds_goal_and_auto_approve():
    args = main_cli._applyMentionShorthand(["@9to5", "fix", "tests", "--hours", "2"])

    assert args == ["--goal", "fix tests", "--auto-approve", "--hours", "2"]


def test_retry_failed_subtasks_resets_only_failed():
    class State:
        def __init__(self):
            self.subtasks = [
                {"subtask_id": "a", "status": "failed"},
                {"subtask_id": "b", "status": "done"},
            ]

        def updateSubtask(self, sid, **fields):
            next(s for s in self.subtasks if s["subtask_id"] == sid).update(fields)

    state = State()
    assert main_cli.retryFailedSubtasks(state) == 1
    assert state.subtasks[0]["status"] == "pending"
    assert state.subtasks[1]["status"] == "done"
