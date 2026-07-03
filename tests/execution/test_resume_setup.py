"""_resumeSetup calls reconcileResume when STEP_RESUME_ENABLED, else blind reset (today)."""
import config
from platform_core.orchestration.run_phase_mixin import OrchestratorRunPhaseMixin


class _Stub(OrchestratorRunPhaseMixin):
    def __init__(self):
        self.obs = type("O", (), {"readNote": lambda *a, **k: "doc"})()

    def _prepareSelfReferential(self, *a, **k):
        pass


class _State:
    def __init__(self):
        self.task_id = "run-1"
        self.meta = {"is_self_referential": False}
        self.subtasks = [{"subtask_id": "st-001", "status": "in_progress", "title": "A"}]

    def updateSubtask(self, sid, **f):
        for s in self.subtasks:
            if s["subtask_id"] == sid:
                s.update(f)

    def architectNoteRel(self):
        return "x"


class _Dash:
    def update(self, *a, **k):
        pass


def test_resume_setup_uses_reconcile_when_enabled(monkeypatch):
    monkeypatch.setattr(config, "STEP_RESUME_ENABLED", True)
    called = {}
    import platform_core.orchestration.step_resume as sr
    monkeypatch.setattr(sr, "reconcileResume", lambda state, **k: called.setdefault("hit", True))
    _Stub()._resumeSetup(_State(), "wd", None, _Dash())
    assert called.get("hit") is True


def test_resume_setup_blind_reset_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "STEP_RESUME_ENABLED", False)
    st = _State()
    _Stub()._resumeSetup(st, "wd", None, _Dash())
    assert st.subtasks[0]["status"] == "pending"     # today's behavior preserved
