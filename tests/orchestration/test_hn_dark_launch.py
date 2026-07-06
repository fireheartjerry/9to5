"""Dark-launch equivalence: with HUMAN_NATURE_ENABLED off, every psyche-v2 coupling and
hot-path hook is a no-op that writes nothing to state.meta and never raises. This is the
byte-identical-run safety invariant for the human-nature layer.

RUN/TEST: python -m pytest tests/orchestration/test_hn_dark_launch.py
"""
from __future__ import annotations

import config
from platform_core.orchestration.human_nature_bridge import (
    biasEffortTiered,
    inventorCouple,
    instinctCheck,
    maybeDebate,
    opinionVote,
    requestDeepen,
    runPreambleHooks,
)


class _FakeState:
    def __init__(self):
        self.data = {"meta": {}}
        self.subtasks = []
        self.task_id = "t-dark"

    @property
    def meta(self):
        return self.data["meta"]


class _FakeCoordinator:
    def __init__(self):
        self.called = 0

    def resolveContested(self, messages):  # noqa: N802 -- mirror real signature
        self.called += 1
        return []


def _hn_off(monkeypatch):
    for flag in (
        "HUMAN_NATURE_ENABLED", "HN_INSTINCT", "HN_VERIFY_DEEPEN", "HN_SOCIETY_TRIGGER",
        "HN_PLAN_AUTHORITY", "HN_EXEC_AUTHORITY", "HN_INVENTOR_COUPLING", "HN_MOOD_PERSIST",
    ):
        monkeypatch.setattr(config, flag, False, raising=False)


def test_opinion_vote_noop_when_off(monkeypatch):
    _hn_off(monkeypatch)
    st = _FakeState()
    assert opinionVote(st) == []
    assert "hn_votes" not in st.meta


def test_maybe_debate_noop_when_off(monkeypatch):
    _hn_off(monkeypatch)
    st, coord = _FakeState(), _FakeCoordinator()
    assert maybeDebate(st, coord) is None
    assert coord.called == 0
    assert "hn_debate" not in st.meta


def test_instinct_check_noop_when_off(monkeypatch):
    _hn_off(monkeypatch)
    st = _FakeState()
    st.meta["hn_event_log"] = [
        {"type": "PATCH_LARGE", "seq": 0, "fields": {}},
        {"type": "TESTS_SKIPPED", "seq": 1, "fields": {}},
        {"type": "CONFIDENCE_HIGH", "seq": 2, "fields": {}},
    ]
    assert instinctCheck(st) is None
    assert "hn_instinct" not in st.meta


def test_request_deepen_noop_when_off(monkeypatch):
    _hn_off(monkeypatch)
    st = _FakeState()
    assert requestDeepen(st, reason="x", conviction=0.99) == 0
    assert "hn_verify_deepen" not in st.meta


def test_inventor_couple_noop_when_off(monkeypatch):
    _hn_off(monkeypatch)
    st = _FakeState()
    assert inventorCouple(st) is None
    assert "hn_inventor" not in st.meta


def test_bias_effort_tiered_noop_when_off(monkeypatch):
    _hn_off(monkeypatch)
    # Even at a hold tier with deliberate routing, effort is unchanged when the exec-authority flag is off.
    assert biasEffortTiered("default", "deliberate", "hold") == "default"


def test_preamble_noop_when_off(monkeypatch):
    _hn_off(monkeypatch)
    st = _FakeState()
    runPreambleHooks(st)
    assert st.meta == {}  # no self_state, no hn_event_log written


def test_couplings_never_raise_on_garbage_state(monkeypatch):
    # Enable the flags but hand each coupling a malformed state; best-effort must swallow it.
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True, raising=False)
    for flag in ("HN_INSTINCT", "HN_VERIFY_DEEPEN", "HN_SOCIETY_TRIGGER", "HN_PLAN_AUTHORITY"):
        monkeypatch.setattr(config, flag, True, raising=False)
    garbage = object()
    assert opinionVote(garbage) == []
    assert maybeDebate(garbage, None) is None
    assert instinctCheck(garbage) is None
    assert requestDeepen(garbage) == 0
    assert inventorCouple(garbage) is None
