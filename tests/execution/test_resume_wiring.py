"""resume_session_id persists to subtask['session']; resumable subtasks seed attempt 1."""
import config
from state.task import TaskState


def test_set_resume_session_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    st = TaskState.create("g", 1.0)
    st.addSubtask("A", "")
    st.setResumeSession("st-001", "sess-42")
    assert st.getSubtask("st-001")["session"]["resume_session_id"] == "sess-42"
    # Idempotent + preserves other session keys.
    st.updateSubtask("st-001", session={**st.getSubtask("st-001")["session"], "effort": "high"})
    st.setResumeSession("st-001", "sess-99")
    sess = st.getSubtask("st-001")["session"]
    assert sess["resume_session_id"] == "sess-99" and sess["effort"] == "high"


def test_seed_resume_context_reads_session(monkeypatch):
    from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin
    monkeypatch.setattr(config, "STEP_RESUME_ENABLED", True)
    sub = {"subtask_id": "st-001",
           "session": {"resumable": True, "resume_block": "## Resume...\n[x] step 0",
                       "resume_session_id": "sess-7"}}
    fb, resume = OrchestratorExecuteMixin._seedResumeContext(sub)
    assert resume == "sess-7"
    assert "Resume" in fb


def test_seed_resume_context_off_when_flag_disabled(monkeypatch):
    from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin
    monkeypatch.setattr(config, "STEP_RESUME_ENABLED", False)
    sub = {"subtask_id": "st-001", "session": {"resumable": True, "resume_block": "x",
                                               "resume_session_id": "s"}}
    fb, resume = OrchestratorExecuteMixin._seedResumeContext(sub)
    assert fb is None and resume is None
