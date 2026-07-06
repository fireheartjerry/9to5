"""Tests for platform_core/orchestration/human_nature_bridge/society.py.

maybeDebate reads the psyche's faculty disagreement (opinion/intuition/instinct signals
+ self-model calibration) from state.meta, scores dissonance via human_nature.conflict,
and -- only when the route is "debate" and rate-limit budget remains -- calls
coordinator.resolveContested (best-effort, defensive getattr) to spawn a heterogeneous
critic lens. It is gated on HUMAN_NATURE_ENABLED and HN_SOCIETY_TRIGGER, best-effort
(never raises), and rate-limited via HN_DEBATE_RATE_LIMIT.
"""
from __future__ import annotations

import config


class _FakeCoordinator:
    def __init__(self) -> None:
        self.calls: list = []

    def resolveContested(self, messages):
        self.calls.append(messages)
        return [{"subtask_id": "st-1", "verdict": "keep"}]


def _disagreeing_state() -> dict:
    return {
        "meta": {
            "hn_opinion_signal": 1.0,
            "hn_intuition_signal": -1.0,
            "hn_instinct_signal": 1.0,
            "self_state": {"competence": 0.0},
        }
    }


def _agreeing_state() -> dict:
    return {
        "meta": {
            "hn_opinion_signal": 1.0,
            "hn_intuition_signal": 1.0,
            "hn_instinct_signal": 1.0,
            "self_state": {"competence": 1.0},
        }
    }


def test_maybe_debate_off_is_noop_when_hn_disabled(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import society

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", False)
    monkeypatch.setattr(config, "HN_SOCIETY_TRIGGER", True)
    state = _disagreeing_state()
    coordinator = _FakeCoordinator()

    assert society.maybeDebate(state, coordinator) is None
    assert "hn_debate" not in state["meta"]
    assert coordinator.calls == []


def test_maybe_debate_off_is_noop_when_trigger_disabled(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import society

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_SOCIETY_TRIGGER", False)
    state = _disagreeing_state()
    coordinator = _FakeCoordinator()

    assert society.maybeDebate(state, coordinator) is None
    assert "hn_debate" not in state["meta"]
    assert coordinator.calls == []


def test_maybe_debate_fires_on_strong_disagreement(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import society

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_SOCIETY_TRIGGER", True)
    monkeypatch.setattr(config, "HN_DEBATE_RATE_LIMIT", 1)
    state = _disagreeing_state()
    coordinator = _FakeCoordinator()

    record = society.maybeDebate(state, coordinator)

    assert record is not None
    assert record["route"] == "debate"
    assert record["fired"] is True
    assert record["dissonance"] >= 0.7
    assert len(coordinator.calls) == 1
    assert state["meta"]["hn_debate"] == [record]
    # the opposing/critic lens was spawned alongside the incumbent verdict.
    roster = {m.get("role") for m in coordinator.calls[0]}
    assert {"skeptic"}.issubset(roster)


def test_maybe_debate_agreeing_signals_route_none_and_no_call(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import society

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_SOCIETY_TRIGGER", True)
    state = _agreeing_state()
    coordinator = _FakeCoordinator()

    record = society.maybeDebate(state, coordinator)

    assert record is not None
    assert record["route"] == "none"
    assert record["fired"] is False
    assert coordinator.calls == []
    assert state["meta"]["hn_debate"] == [record]


def test_maybe_debate_rate_limited_after_budget_exhausted(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import society

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_SOCIETY_TRIGGER", True)
    monkeypatch.setattr(config, "HN_DEBATE_RATE_LIMIT", 1)
    state = _disagreeing_state()
    coordinator = _FakeCoordinator()

    first = society.maybeDebate(state, coordinator)
    assert first["fired"] is True
    assert len(coordinator.calls) == 1

    second = society.maybeDebate(state, coordinator)
    assert second["fired"] is False
    assert len(coordinator.calls) == 1  # unchanged -- budget exhausted, no new debate
    assert len(state["meta"]["hn_debate"]) == 2


def test_maybe_debate_no_coordinator_is_noop_but_still_records(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import society

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_SOCIETY_TRIGGER", True)
    state = _disagreeing_state()

    record = society.maybeDebate(state, None)

    assert record is not None
    assert record["route"] == "debate"
    assert record["fired"] is False


def test_maybe_debate_coordinator_missing_resolve_contested_never_raises(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import society

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_SOCIETY_TRIGGER", True)
    state = _disagreeing_state()

    class _BareCoordinator:
        pass

    record = society.maybeDebate(state, _BareCoordinator())

    assert record is not None
    assert record["fired"] is False


def test_maybe_debate_coordinator_raising_never_propagates(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import society

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_SOCIETY_TRIGGER", True)
    state = _disagreeing_state()

    class _BoomCoordinator:
        def resolveContested(self, messages):
            raise RuntimeError("debate engine down")

    record = society.maybeDebate(state, _BoomCoordinator())

    assert record is not None
    assert record["fired"] is False  # the raise was swallowed, not fired
    assert state["meta"]["hn_debate"] == [record]


def test_maybe_debate_surfaces_dashboard_event_on_fire(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import society

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_SOCIETY_TRIGGER", True)
    state = _disagreeing_state()
    coordinator = _FakeCoordinator()
    events = []

    class _Dash:
        def event(self, msg):
            events.append(msg)

    society.maybeDebate(state, coordinator, _Dash())

    assert any("debate" in e for e in events), events


def test_maybe_debate_never_raises_on_malformed_meta(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import society

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_SOCIETY_TRIGGER", True)

    assert society.maybeDebate({"meta": None}, _FakeCoordinator()) is None
