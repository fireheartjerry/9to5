from state.task_schema import TaskState

def test_create_has_human_nature_meta_fields():
    ts = TaskState.create("ship the thing", 1.0)
    meta = ts.data["meta"]
    for key in ("self_state", "autonomy", "charter_version"):
        assert key in meta
        assert meta[key] is None
