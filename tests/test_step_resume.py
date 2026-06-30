"""planSignature stability + resumePlan markers + reconcileResume gate."""
from memory import experience_schema as es
from platform_core.orchestration import step_resume as sr
from state.task import TaskState


def _state(tmp_path, monkeypatch):
    monkeypatch.setattr(es.config, "EXPERIENCE_DB_PATH", tmp_path / "experience.db")
    monkeypatch.setattr(TaskState.create.__globals__["config"], "STATE_DIR", tmp_path)
    es._reset_schema_cache()
    es.init(tmp_path / "experience.db")
    st = TaskState.create("goal", 1.0)
    st.addSubtask("Build A", "", verify={"cmd": "pytest a", "expect": "ok"})
    st.addSubtask("Build B", "", verify={"cmd": "pytest b", "expect": "ok"})
    return st


def test_plan_signature_stable_and_sensitive(tmp_path, monkeypatch):
    st = _state(tmp_path, monkeypatch)
    sig1 = sr.planSignature(st)
    assert sig1 == sr.planSignature(st)               # stable under no-op reload
    st.updateSubtask("st-002", verify={"cmd": "pytest b CHANGED", "expect": "ok"})
    assert sr.planSignature(st) != sig1               # changes when verify.cmd mutates
    es._reset_schema_cache()


def test_resume_plan_markers_and_footer(tmp_path, monkeypatch):
    st = _state(tmp_path, monkeypatch)
    sub = st.getSubtask("st-001")
    steps = [{"step_idx": 0, "summary": "edit a.py", "tool": "Edit"},
             {"step_idx": 1, "summary": "run tests", "tool": "Bash"}]
    out = sr.resumePlan(st, sub, steps)
    assert "[x]" in out["resume_block"] and "[→]" in out["resume_block"]
    assert "Do NOT rewrite the plan" in out["resume_block"]
    assert out["current_idx"] == 2


def test_reconcile_keeps_on_sig_match(tmp_path, monkeypatch):
    from memory import experience_journal as ej
    db = tmp_path / "experience.db"
    st = _state(tmp_path, monkeypatch)
    st.updateSubtask("st-001", status="in_progress")
    sig = sr.planSignature(st)
    ej.appendStep(st.task_id, "st-001", 1, 0, "tool", "Edit", "x", {}, sig, "sess-1", db_path=db)
    sr.reconcileResume(st, db_path=db)
    sub = st.getSubtask("st-001")
    assert sub["status"] == "pending"                 # re-schedulable
    assert sub["session"]["resumable"] is True
    assert sub["session"]["resume_session_id"] == "sess-1"
    assert "[x]" in sub["session"]["resume_block"]
    es._reset_schema_cache()


def test_reconcile_resets_on_sig_mismatch(tmp_path, monkeypatch):
    from memory import experience_journal as ej
    db = tmp_path / "experience.db"
    st = _state(tmp_path, monkeypatch)
    st.updateSubtask("st-001", status="in_progress")
    ej.appendStep(st.task_id, "st-001", 1, 0, "tool", "Edit", "x", {}, "STALE-SIG", "s",
                  db_path=db)
    sr.reconcileResume(st, db_path=db)
    sub = st.getSubtask("st-001")
    assert sub["status"] == "pending"
    assert not sub["session"].get("resumable")        # NOT resumable -> clean rerun
    assert ej.lastStepIdx(st.task_id, "st-001", 1, db_path=db) == -1   # journal superseded
    es._reset_schema_cache()


def test_reconcile_empty_journal_resets(tmp_path, monkeypatch):
    db = tmp_path / "experience.db"
    st = _state(tmp_path, monkeypatch)
    st.updateSubtask("st-001", status="in_progress")
    sr.reconcileResume(st, db_path=db)
    assert st.getSubtask("st-001")["status"] == "pending"
    assert not st.getSubtask("st-001")["session"].get("resumable")
    es._reset_schema_cache()
