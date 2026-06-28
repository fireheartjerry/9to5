"""Tests for comparative-intelligence deltas (compare_run)."""
import config
from memory import experience


def _make_run(task_id, *, status, started, completed, replans=0, advs=0, done=1, innovation=None):
    subs = [{"subtask_id": "st-001", "status": "done" if done else "failed",
             "completed_at": completed}]
    meta = {"goal_raw": "g", "started_at": started, "status": status}
    if innovation is not None:
        meta["discovery_report"] = {"innovation_rate": innovation}
    return {
        "task_id": task_id,
        "meta": meta,
        "plan": {"subtasks": subs},
        "notifications": [{"kind": "replan"}] * replans,
        "adversary_reviews": [{}] * advs,
        "obsidian": {},
    }


def _save(tmp_path, data):
    import json
    p = tmp_path / f"{data['task_id']}.json"
    p.write_text(json.dumps(data), encoding="utf-8")


def test_compare_run_returns_string_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    # two prior terminal runs + the current one
    _save(tmp_path, _make_run("prior-1", status="done",
                              started="2026-06-01T10:00:00+00:00",
                              completed="2026-06-01T11:00:00+00:00", replans=2, advs=3, innovation=0.40))
    _save(tmp_path, _make_run("prior-2", status="done",
                              started="2026-06-02T10:00:00+00:00",
                              completed="2026-06-02T11:00:00+00:00", replans=1, advs=1, innovation=0.42))
    _save(tmp_path, _make_run("current", status="done",
                              started="2026-06-03T10:00:00+00:00",
                              completed="2026-06-03T10:30:00+00:00", replans=1, advs=0, innovation=0.73))
    out = experience.compare_run("current")
    for k in ("pace", "innovation", "adversary", "replans"):
        assert k in out and isinstance(out[k], str)
    assert "raw" in out and isinstance(out["raw"], dict)
    assert "avg" in out["adversary"]   # references the historical average


def test_compare_run_no_history(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    _save(tmp_path, _make_run("solo", status="done",
                              started="2026-06-03T10:00:00+00:00",
                              completed="2026-06-03T10:30:00+00:00"))
    out = experience.compare_run("solo")   # must not raise; tolerant of zero history
    assert isinstance(out, dict)
    for k in ("pace", "innovation", "adversary", "replans"):
        assert k in out


def test_compare_run_missing_task_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    out = experience.compare_run("does-not-exist")
    assert isinstance(out, dict)
