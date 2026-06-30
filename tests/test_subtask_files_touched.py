"""addSubtask carries planner-authored files_touched + a claimed_by slot (additive, default-safe)."""
import config
from state.task import TaskState


def test_addsubtask_new_fields_default_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    st = TaskState.create("g", 1.0)
    s = st.addSubtask("A", "")
    assert s["files_touched"] == []          # default: unknown -> serialize (conservative)
    assert s["claimed_by"] is None


def test_addsubtask_accepts_files_touched(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    st = TaskState.create("g", 1.0)
    s = st.addSubtask("A", "", files_touched=["a.py", "b.py"])
    assert s["files_touched"] == ["a.py", "b.py"]
