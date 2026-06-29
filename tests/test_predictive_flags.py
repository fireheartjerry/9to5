"""Predictive flag engine: heuristics + rate limiting (all data injected, no DB/Ollama)."""
from notifications import predictive


class _State:
    task_id = "t1"
    meta = {"goal_raw": "x", "started_at": "2026-06-28T09:00:00",
            "deadline_at": "2026-06-28T10:00:00"}
    subtasks = [
        {"subtask_id": "st-003", "title": "touch hot file", "status": "in_progress",
         "description": "edit notifications/discord_client.py", "started_at": "2026-06-28T09:50:00"},
    ]
    data = {"notifications": [], "adversary_reviews": []}


def test_file_hotspot_flag():
    eng = predictive.PredictiveFlags()
    hist = {"file_hotspots": {"notifications/discord_client.py": 6}}
    flags = eng.evaluate(_State(), history=hist)
    assert any(f.signal == "file_hotspot" for f in flags)


def test_verify_similarity_flag():
    eng = predictive.PredictiveFlags()
    st = _State()
    st.subtasks = [{"subtask_id": "st-003", "title": "t", "status": "pending",
                    "verify": {"cmd": "python -m pytest tests/test_pool.py -q"}}]
    hist = {"failing_specs": ["python -m pytest tests/test_pool.py -q"]}
    flags = eng.evaluate(st, history=hist)
    assert any(f.signal == "verify_similarity" for f in flags)


def test_rate_limit_one_per_window():
    eng = predictive.PredictiveFlags()
    hist = {"file_hotspots": {"notifications/discord_client.py": 6}}
    first = eng.emit_due(_State(), history=hist, now=1000.0)
    second = eng.emit_due(_State(), history=hist, now=1000.5)
    assert first is not None
    assert second is None  # within 90s window AND same signal already seen


def test_same_signal_never_twice():
    eng = predictive.PredictiveFlags()
    hist = {"file_hotspots": {"notifications/discord_client.py": 6}}
    eng.emit_due(_State(), history=hist, now=0.0)
    later = eng.emit_due(_State(), history=hist, now=10_000.0)  # window elapsed
    assert later is None  # signal already seen this run


def test_disabled_returns_nothing(monkeypatch):
    import config
    monkeypatch.setattr(config, "PREDICTIVE_FLAGS_ENABLED", False)
    eng = predictive.PredictiveFlags()
    assert eng.emit_due(_State(), history={"file_hotspots": {"x.py": 9}}, now=0.0) is None


def test_pace_flag_from_injected_fracs():
    eng = predictive.PredictiveFlags()
    hist = {"time_remaining_frac": 0.1, "work_remaining_frac": 0.6}
    assert any(f.signal == "pace" for f in eng.evaluate(_State(), history=hist))


def test_no_flags_on_empty_history():
    eng = predictive.PredictiveFlags()
    assert eng.evaluate(_State(), history={}) == []
