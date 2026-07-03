"""agents/hooks_obsidian.py -- the write_obsidian PostToolUse hook.

Previously untested (RUN/TEST said "no mapped test"): writeObsidian() only had implicit
coverage of its early-exit paths (no active task). This covers the happy path -- an
Edit/Write/MultiEdit during an in-progress subtask must append one line to that subtask's
Obsidian note -- plus the early-exit paths that keep it a pure telemetry hook (never blocks).
"""
from __future__ import annotations

from unittest import mock

import pytest

from agents.hooks_obsidian import writeObsidian


class _FakeState:
    def __init__(self, subtasks):
        self.subtasks = subtasks

    def getSubtask(self, sid):
        return next((s for s in self.subtasks if s["subtask_id"] == sid), None)

    def subtaskNoteRel(self, sid):
        return f"tasks/task-1/{sid}.md"


def test_writeobsidian_appends_note_for_in_progress_subtask(monkeypatch):
    state = _FakeState([{"subtask_id": "st-001", "status": "in_progress"}])
    monkeypatch.setattr("agents.hooks_obsidian._resolveState", lambda: (state, False))

    with mock.patch("memory.obsidian.ObsidianClient.appendNote") as m_append:
        with pytest.raises(SystemExit) as ei:
            writeObsidian({"tool_name": "Edit",
                            "tool_input": {"file_path": "agents/hooks.py"}})

    assert ei.value.code == 0
    m_append.assert_called_once()
    rel_path, line = m_append.call_args[0]
    assert rel_path == "tasks/task-1/st-001.md"
    assert "Edit" in line and "agents/hooks.py" in line


def test_writeobsidian_prefers_explicit_subtask_env_var(monkeypatch):
    state = _FakeState([
        {"subtask_id": "st-001", "status": "in_progress"},
        {"subtask_id": "st-002", "status": "in_progress"},
    ])
    monkeypatch.setattr("agents.hooks_obsidian._resolveState", lambda: (state, False))
    monkeypatch.setenv("NINE_TO_FIVE_SUBTASK_ID", "st-002")

    with mock.patch("memory.obsidian.ObsidianClient.appendNote") as m_append:
        with pytest.raises(SystemExit):
            writeObsidian({"tool_name": "Write",
                            "tool_input": {"file_path": "docs/ARCHITECTURE.md"}})

    rel_path, _line = m_append.call_args[0]
    assert rel_path == "tasks/task-1/st-002.md"


def test_writeobsidian_no_active_task_exits_quietly_without_writing(monkeypatch):
    monkeypatch.setattr("agents.hooks_obsidian._resolveState", lambda: (None, False))

    with mock.patch("memory.obsidian.ObsidianClient.appendNote") as m_append:
        with pytest.raises(SystemExit) as ei:
            writeObsidian({"tool_name": "Edit", "tool_input": {"file_path": "x.py"}})

    assert ei.value.code == 0
    m_append.assert_not_called()


def test_writeobsidian_ignores_non_file_tools(monkeypatch):
    called = []
    monkeypatch.setattr("agents.hooks_obsidian._resolveState",
                        lambda: called.append(1) or (None, False))

    with pytest.raises(SystemExit) as ei:
        writeObsidian({"tool_name": "Bash", "tool_input": {"command": "ls"}})

    assert ei.value.code == 0
    assert not called  # short-circuits before ever resolving state
