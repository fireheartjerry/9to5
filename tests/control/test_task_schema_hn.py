from state.task_schema import TaskState

def test_create_has_parked_layer_meta_fields():
    """Vestigial meta keys kept for the parked human-nature layer (code at a7b1b2d)."""
    ts = TaskState.create("ship the thing", 1.0)
    meta = ts.data["meta"]
    for key in ("self_state", "autonomy", "charter_version"):
        assert key in meta
        assert meta[key] is None
