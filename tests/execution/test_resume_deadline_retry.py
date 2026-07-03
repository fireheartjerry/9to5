"""Resume-time deadline extension and failed-subtask retry (main._extendResumeDeadline /
main._retryFailedSubtasks). Covers the bug where resuming an already-expired-deadline task
immediately re-hit the time horizon and re-finalized as 'partial'."""
from datetime import datetime, timedelta

import config
from state.task import TaskState
from main import _extendResumeDeadline, _retryFailedSubtasks


def _mk(tmp_path, monkeypatch, hours=1.0):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(config, "CONTROL_DIR", tmp_path, raising=False)
    st = TaskState.create("Fix the windows path bug", hours)
    st.save()
    return st


def _expire(state) -> str:
    """Push deadline_at into the past; returns the expired timestamp."""
    past = (datetime.now().astimezone() - timedelta(hours=2)).isoformat(timespec="seconds")
    state.meta["deadline_at"] = past
    state.save()
    return past


def test_extend_resume_deadline_noop_when_not_passed(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    before = st.meta["deadline_at"]
    _extendResumeDeadline(st, None)
    assert st.meta["deadline_at"] == before


def test_extend_resume_deadline_recovers_expired_deadline(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch, hours=1.0)
    expired = _expire(st)
    _extendResumeDeadline(st, None)
    new_deadline = datetime.fromisoformat(st.meta["deadline_at"])
    assert st.meta["deadline_at"] != expired
    assert new_deadline > datetime.now().astimezone()


def test_extend_resume_deadline_explicit_hours_forces_extension(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch, hours=1.0)
    before = st.meta["deadline_at"]  # not expired
    _extendResumeDeadline(st, 3.0)
    new_deadline = datetime.fromisoformat(st.meta["deadline_at"])
    assert st.meta["deadline_at"] != before
    assert new_deadline > datetime.now().astimezone() + timedelta(hours=2.5)


def test_retry_failed_subtasks_resets_only_failed(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    st.addSubtask("a", "a")
    st.addSubtask("b", "b")
    st.addSubtask("c", "c")
    ids = [s["subtask_id"] for s in st.subtasks]
    st.updateSubtask(ids[0], status="failed")
    st.updateSubtask(ids[1], status="done")
    st.updateSubtask(ids[2], status="pending")

    n = _retryFailedSubtasks(st)

    assert n == 1
    statuses = {s["subtask_id"]: s["status"] for s in st.subtasks}
    assert statuses[ids[0]] == "pending"   # was failed -> reset
    assert statuses[ids[1]] == "done"      # untouched
    assert statuses[ids[2]] == "pending"   # untouched (already pending)


def test_retry_failed_subtasks_noop_when_none_failed(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    st.addSubtask("a", "a")
    assert _retryFailedSubtasks(st) == 0
