"""Granular controls: ControlBus boolean signals + op-driven state mutations."""
import config
from state.task import TaskState
from platform_core.runtime.control import ControlBus
from notifications import commands as spine


def _mk(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(config, "CONTROL_DIR", tmp_path, raising=False)
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
