"""Intent injection: schema methods, command routing -> bus op, _applyOps, and spec fold."""
import config
from state.task import TaskState
from platform_core.runtime.control import ControlBus
from notifications import commands as spine


def _mk(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(config, "CONTROL_DIR", tmp_path, raising=False)
    st = TaskState.create("Fix the windows path bug", 1.0)
    st.save()
    return st


def test_add_and_active_intents(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    st.addIntent("focus on the windows edge case")
    assert "windows edge case" in st.activeIntents()[0]


def test_intents_expire_after_two_completions(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    st.addIntent("temporary steer")
    st.addSubtask("a", "a")
    st.addSubtask("b", "b")
    # mark two subtasks terminal -> intent (added at 0 completions) expires at 2
    for s in list(st.subtasks):
        st.updateSubtask(s["subtask_id"], status="done")
    assert st.activeIntents() == []


def test_clear_intents(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    st.addIntent("steer A")
    st.clearIntents()
    assert st.activeIntents() == []


def test_command_intent_pushes_bus_op(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    bus = ControlBus(st.task_id)
    msg = spine.applyCommand(bus, st, spine.Command("intent", "deprioritize cleanup"))
    ops = bus.drainOps()
    assert any(o.get("op") == "intent" and "cleanup" in o.get("text", "") for o in ops)
    assert "intent" in msg.lower()


def test_command_intent_clear_pushes_clear_op(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    bus = ControlBus(st.task_id)
    spine.applyCommand(bus, st, spine.Command("intent", "clear"))
    assert any(o.get("op") == "intent_clear" for o in bus.drainOps())


def test_command_intent_persist_writes_prefs(tmp_path, monkeypatch):
    from memory import user_prefs
    st = _mk(tmp_path, monkeypatch)
    bus = ControlBus(st.task_id)
    spine.applyCommand(bus, st, spine.Command("intent", "persist always run black"))
    prefs = user_prefs.load(path=tmp_path.parent / "user_prefs.json")
    assert any("black" in str(p) for p in prefs["persistent_intents"])


def test_injected_context_take_clears(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    st.addInjectedContext("watch the windows path separator")
    assert st.takeInjectedContext() == ["watch the windows path separator"]
    assert st.takeInjectedContext() == []  # consumed


def test_extend_deadline_moves_deadline(tmp_path, monkeypatch):
    st = _mk(tmp_path, monkeypatch)
    before = st.meta["deadline_at"]
    st.extendDeadline(3600)
    assert st.meta["deadline_at"] != before
