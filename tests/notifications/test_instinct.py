"""Nightclaw instinct: prompt builder + at-most-once-per-run firing (chat injected)."""
from notifications import instinct


class _State:
    task_id = "t1"
    meta = {"goal_raw": "wire pool", "status": "executing", "instinct_flags": []}
    subtasks = [{"subtask_id": "st-001", "title": "a", "status": "done"}]
    data = {"notifications": [{"at": "t", "kind": "subtask_done", "detail": "st-001"}],
            "adversary_reviews": []}


def test_build_prompt_includes_state_and_experience():
    eng = instinct.NightclawInstinct()
    system, user = eng.build_prompt(_State(), reflections=[{"approach": "used pool guard"}],
                                    failure_modes=[{"root_cause": "timing"}], events=[])
    assert "pattern" in system.lower()
    assert "pool guard" in user or "timing" in user


def test_fires_on_nonempty_response():
    eng = instinct.NightclawInstinct()
    out = eng.maybe_fire(_State(), reflections=[], failure_modes=[],
                         chat=lambda s, u: "Something feels off about the pool ordering.")
    assert out and "off" in out.lower()


def test_silent_on_empty_response():
    eng = instinct.NightclawInstinct()
    assert eng.maybe_fire(_State(), reflections=[], failure_modes=[],
                          chat=lambda s, u: "  ") is None


def test_at_most_once_per_run():
    eng = instinct.NightclawInstinct()
    st = _State()
    st.meta["instinct_flags"] = [{"text": "already flagged"}]
    out = eng.maybe_fire(st, reflections=[], failure_modes=[],
                         chat=lambda s, u: "new signal", already_fired=True)
    assert out is None


def test_offline_is_silent():
    eng = instinct.NightclawInstinct()

    def boom(s, u):
        raise RuntimeError("down")
    assert eng.maybe_fire(_State(), reflections=[], failure_modes=[], chat=boom) is None
