"""Granular controls: ControlBus boolean signals + op-driven state mutations."""
import threading
from unittest import mock

import pytest

import config
from state.task import TaskState
from platform_core.runtime.control import AbortRun, ControlBus
from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin
from notifications import commands as spine


def _mk(tmp_path, monkeypatch):
    # SEPARATE dirs: task state and control bus share the <task_id>.json filename, so a
    # single shared dir lets state.save() clobber the bus file (silently eating !abort).
    state_dir = tmp_path / "tasks"
    control_dir = tmp_path / "control"
    state_dir.mkdir(exist_ok=True)
    control_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "STATE_DIR", state_dir, raising=False)
    monkeypatch.setattr(config, "CONTROL_DIR", control_dir, raising=False)
    st = TaskState.create("goal", 1.0)
    st.addSubtask("a", "a")
    st.save()
    return st


def test_kill_sets_and_clears(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    bus = ControlBus(st.task_id)
    spine.applyCommand(bus, st, spine.Command("kill", ""))
    assert bus.isKillSubprocess() is True
    bus.clearKillSubprocess()
    assert bus.isKillSubprocess() is False


def test_replan_sets_force_flag(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    bus = ControlBus(st.task_id)
    spine.applyCommand(bus, st, spine.Command("replan", ""))
    assert bus.isForceReplan() is True


def test_deadline_extend_op_updates_meta(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    before = st.meta["deadline_at"]
    st.extendDeadline(3600)
    assert st.meta["deadline_at"] != before


def test_set_effort_op_records_override(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    sid = st.subtasks[0]["subtask_id"]
    st.updateSubtask(sid, effort_override="high")
    assert st.getSubtask(sid)["effort_override"] == "high"


def test_effort_command_pushes_run_effort_op(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    bus = ControlBus(st.task_id)
    spine.applyCommand(bus, st, spine.Command("effort", "high"))
    assert any(o.get("op") == "set_run_effort" and o.get("level") == "high"
               for o in bus.drainOps())


def test_inject_command_pushes_inject_op(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    bus = ControlBus(st.task_id)
    spine.applyCommand(bus, st, spine.Command("inject", "mind the windows path sep"))
    assert any(o.get("op") == "inject_context" for o in bus.drainOps())


def test_set_effort_command_validates(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    bus = ControlBus(st.task_id)
    msg = spine.applyCommand(bus, st, spine.Command("set-effort", "st-001 high"))
    assert "st-001" in msg
    bad = spine.applyCommand(bus, st, spine.Command("set-effort", "nope huge"))
    assert "usage" in bad.lower()


# =====================================================================
# R6 operator-kill: an operator_killed attempt is control flow -- it must
# not burn an attempt slot, must skip verification, and must go straight
# to the loop's kill/abort control branch.
# =====================================================================

_KILLED_RESULT = {"ok": False, "returncode": -1, "stdout": "partial",
                  "stderr": "OPERATOR KILLED (abort/kill signal)",
                  "subtype": "operator_killed"}
_PASSING_RESULT = {"ok": True, "returncode": 0, "stdout": "done", "stderr": ""}


class _LoopHost(OrchestratorExecuteMixin):
    """Minimal host exposing only what _runAttemptLoop touches."""

    def __init__(self):
        self._state_lock = threading.RLock()

    def _translateDiscord(self, bus, state):
        pass

    def _waitWhilePaused(self, state, bus, dashboard, label=""):
        pass

    def _deadlinePassed(self, state):
        return False


def _fakeAttempt(calls, kills_before_pass):
    """Stub _runOneAttempt: N operator-killed results, then one passing attempt."""

    def _attempt(state, subtask, architect_doc, exec_cwd, bus, dashboard, sid,
                 verify_spec, failure_feedback, resume_session, attempt, env_ctx=None):
        calls.append(attempt)
        if len(calls) <= kills_before_pass:
            return ({}, dict(_KILLED_RESULT), {"passed": False, "operator_killed": True},
                    "partial", False, None, failure_feedback)
        return ({}, dict(_PASSING_RESULT), {"passed": True}, "done", True, None, None)

    return _attempt


def test_operator_kill_does_not_burn_attempt_slot(tmp_path, monkeypatch):
    """Kills equal to MAX_SUBTASK_ATTEMPTS would exhaust the loop pre-R6; now the slot is
    restored each time and the real attempt still runs (and passes) at attempt 1."""
    st = _mk(tmp_path, monkeypatch)
    sid = st.subtasks[0]["subtask_id"]
    monkeypatch.setattr(config, "MAX_SUBTASK_ATTEMPTS", 3, raising=False)
    host = _LoopHost()
    calls = []
    host._runOneAttempt = _fakeAttempt(calls, kills_before_pass=3)
    spec, result, vresult, combined, passed, attempt = host._runAttemptLoop(
        st, st.getSubtask(sid), "arch", str(tmp_path), ControlBus(st.task_id),
        mock.Mock(), sid, None)
    assert passed is True
    assert len(calls) == 4          # 3 kills + the real attempt all ran
    assert calls == [1, 1, 1, 1]    # no kill ever consumed a slot
    assert attempt == 1


def test_operator_kill_at_deadline_stops_respawning(tmp_path, monkeypatch):
    """A deadline-driven cancel must NOT loop forever respawning instantly-killed attempts."""
    st = _mk(tmp_path, monkeypatch)
    sid = st.subtasks[0]["subtask_id"]
    monkeypatch.setattr(config, "MAX_SUBTASK_ATTEMPTS", 3, raising=False)
    host = _LoopHost()
    host._deadlinePassed = lambda state: True
    calls = []
    host._runOneAttempt = _fakeAttempt(calls, kills_before_pass=99)
    spec, result, vresult, combined, passed, attempt = host._runAttemptLoop(
        st, st.getSubtask(sid), "arch", str(tmp_path), ControlBus(st.task_id),
        mock.Mock(), sid, None)
    assert passed is False
    assert len(calls) == 1          # exactly one killed attempt, then the loop broke


def test_operator_kill_with_abort_raises_abortrun(tmp_path, monkeypatch):
    """!abort triggered the kill -> the loop surfaces AbortRun within one iteration."""
    st = _mk(tmp_path, monkeypatch)
    sid = st.subtasks[0]["subtask_id"]
    bus = ControlBus(st.task_id)
    bus.requestAbort()
    host = _LoopHost()
    calls = []
    host._runOneAttempt = _fakeAttempt(calls, kills_before_pass=99)
    with pytest.raises(AbortRun):
        host._runAttemptLoop(st, st.getSubtask(sid), "arch", str(tmp_path), bus,
                             mock.Mock(), sid, None)
    assert len(calls) == 1


class _KillBus:
    """Bus double: kill flag set (as the watcher leaves it), abort off."""

    def __init__(self):
        self.kill = True
        self.kill_cleared = False

    def isAbort(self):
        return False

    def isKillSubprocess(self):
        return self.kill

    def clearKillSubprocess(self):
        self.kill = False
        self.kill_cleared = True


def test_operator_killed_attempt_skips_verify_and_keeps_feedback(tmp_path, monkeypatch):
    """_runOneAttempt on an operator_killed result: no verification runs, no failure
    feedback is synthesized (the incoming feedback rides through), and the kill flag
    is cleared by the existing control branch."""
    st = _mk(tmp_path, monkeypatch)
    sid = st.subtasks[0]["subtask_id"]
    monkeypatch.setattr(config, "SEMANTIC_SAFETY_ENABLED", False, raising=False)
    host = _LoopHost()
    host.authorInvocationSpec = lambda *a, **k: {"effort_level": "default"}
    host._selectExecutor = lambda spec: (lambda spec_, **kw: dict(_KILLED_RESULT))
    host._run_claude = object()   # hands is not the claude path -> no feed/trajectory wiring
    host._runAttemptVerify = \
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("verify must not run"))
    bus = _KillBus()
    out = host._runOneAttempt(st, st.getSubtask(sid), "arch", str(tmp_path), bus,
                              mock.Mock(), sid, None, "prior feedback", None, 1)
    spec, result, vresult, combined, passed, resume_session, failure_feedback = out
    assert result["subtype"] == "operator_killed"
    assert passed is False
    assert vresult["operator_killed"] is True
    assert failure_feedback == "prior feedback"   # unchanged: nothing synthesized
    assert resume_session is None
    assert bus.kill_cleared is True
