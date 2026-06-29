"""Integration tests for the orchestration surface wiring (arc/reflection/moments)."""
import config
from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin
from platform_core.orchestration.run_phase_mixin import OrchestratorRunPhaseMixin
from notifications.event_bus import get_bus, reset_bus


class _Obs:
    def __init__(self):
        self.notes = []

    def writeNote(self, rel, body):
        self.notes.append((rel, body))
        return {"rel_path": rel}


class _Orch(OrchestratorRunPhaseMixin, OrchestratorExecuteMixin):
    def __init__(self, chat, obs):
        self._ollamaChat = chat
        self.obs = obs


def _state(tmp_path):
    from state.task import TaskState
    s = TaskState.create("harden the rate-limit path", 1.0)
    s.save()
    return s


def test_finalize_surfaces_writes_arc_and_reflection(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    reset_bus()
    bus = get_bus()
    state = _state(tmp_path)
    orch = _Orch(chat=lambda s, u, **k: "I learned the bug was upstream.", obs=_Obs())
    orch._finalizeSurfaces(state, "done", 1, 1, "5m 00s")
    arc = state.meta["arc"]
    assert any(b["text"].startswith("Final —") for b in arc)
    # perfect run (0 replans, 0 adversary) -> a moment is emitted to the bus
    assert any(e["kind"] == "moment" for e in bus.history(last_n=20))
    # reflection saved to disk
    assert (tmp_path / state.task_id / "reflection.md").exists()
    assert orch.obs.notes  # mirrored to Obsidian


def test_surface_subtask_pass_first_verify_and_redemption(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    reset_bus()
    bus = get_bus()
    state = _state(tmp_path)
    st = state.addSubtask("first", "do it")
    state.updateSubtask(st["subtask_id"], status="done")
    orch = _Orch(chat=lambda s, u, **k: "", obs=_Obs())
    orch._surfaceSubtaskPass(state, st["subtask_id"], attempt=3)
    assert any("First subtask closed clean" in b["text"] for b in state.meta["arc"])
    assert any(e["kind"] == "moment" and "Redemption" in e["text"]
               for e in bus.history(last_n=20))


def test_finalize_never_raises_on_bad_chat(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    state = _state(tmp_path)
    orch = _Orch(chat=lambda s, u, **k: (_ for _ in ()).throw(RuntimeError("down")), obs=_Obs())
    orch._finalizeSurfaces(state, "partial", 0, 1, "1m")  # must not raise
