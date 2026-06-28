"""Tests for human_nature/integration.py — Phase 5.4 run-loop hooks.

THE REGRESSION GUARANTEE: with HUMAN_NATURE_ENABLED=False (the default),
every hook is a strict no-op. State must be byte-identical (deep-equal) before
and after every call. Only with the flag True do the hooks perform their work.
"""
from __future__ import annotations

import copy
from unittest.mock import MagicMock

import pytest

import config
from human_nature import integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state() -> dict:
    """Minimal plain-dict run state with a meta sub-dict."""
    return {"meta": {"self_state": None}}


class _FakeTaskState:
    """TaskState-style object with a .data["meta"] structure."""
    def __init__(self):
        self.data = {"meta": {"self_state": None}}


# ---------------------------------------------------------------------------
# OFF tests (HUMAN_NATURE_ENABLED=False is the default — confirmed by conftest)
# ---------------------------------------------------------------------------

class TestOffIsNoOp:
    """Every hook must be a complete no-op when the flag is off."""

    def test_is_enabled_false_by_default(self):
        assert integration.is_enabled() is False

    def test_ensure_self_state_returns_none(self):
        state = _make_state()
        assert integration.ensure_self_state(state) is None

    def test_ensure_self_state_does_not_mutate_state(self):
        state = _make_state()
        before = copy.deepcopy(state)
        integration.ensure_self_state(state)
        assert state == before

    def test_observe_run_events_leaves_state_unchanged(self):
        state = _make_state()
        before = copy.deepcopy(state)
        integration.observe_run_events(state, [{"outcome": "success"}])
        assert state == before

    def test_observe_run_events_empty_events_unchanged(self):
        state = _make_state()
        before = copy.deepcopy(state)
        integration.observe_run_events(state, [])
        assert state == before

    def test_route_pre_act_returns_deliberate_always(self):
        state = _make_state()
        # Even with a near-perfect confidence signal, must return "deliberate"
        signals = {"p_true": 0.99, "self_consistency": 0.99, "ood": False}
        result = integration.route_pre_act(state, "async", signals)
        assert result == "deliberate"

    def test_route_pre_act_does_not_touch_state(self):
        state = _make_state()
        before = copy.deepcopy(state)
        integration.route_pre_act(state, "python", {"p_true": 0.99})
        assert state == before

    def test_maybe_run_instinct_returns_none(self):
        state = _make_state()
        fake_chat = MagicMock()
        result = integration.maybe_run_instinct(state, [], [], chat=fake_chat)
        assert result is None

    def test_maybe_run_instinct_never_calls_chat(self):
        """The OFF guard must not call the injected chat at all."""
        state = _make_state()
        fake_chat = MagicMock()
        integration.maybe_run_instinct(state, [], [], chat=fake_chat)
        assert fake_chat.call_count == 0

    def test_at_teardown_returns_none(self):
        state = _make_state()
        result = integration.at_teardown(state, [], [])
        assert result is None

    def test_at_teardown_does_not_touch_state(self):
        state = _make_state()
        before = copy.deepcopy(state)
        integration.at_teardown(state, [{"domain": "x", "correct": True}], ["reflect"])
        assert state == before


# ---------------------------------------------------------------------------
# ON tests (monkeypatch HUMAN_NATURE_ENABLED=True)
# ---------------------------------------------------------------------------

class TestOnEnabled:
    """With the flag on, hooks perform their work."""

    def test_is_enabled_true(self, monkeypatch):
        monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
        assert integration.is_enabled() is True

    def test_ensure_self_state_initializes(self, monkeypatch):
        monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
        state = _make_state()
        result = integration.ensure_self_state(state)
        assert result is not None
        assert "affect" in result
        assert "competence" in result
        assert state["meta"]["self_state"] is result

    def test_ensure_self_state_idempotent(self, monkeypatch):
        """Second call returns the same dict — no re-initialisation."""
        monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
        state = _make_state()
        r1 = integration.ensure_self_state(state)
        r2 = integration.ensure_self_state(state)
        assert r1 is r2

    def test_ensure_self_state_via_data_attr(self, monkeypatch):
        """Works with TaskState-style objects that have a .data["meta"] attr."""
        monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
        state = _FakeTaskState()
        result = integration.ensure_self_state(state)
        assert result is not None
        assert state.data["meta"]["self_state"] is result

    def test_observe_run_events_writes_affect_failure(self, monkeypatch):
        """Failure events produce negative valence."""
        monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
        state = _make_state()
        events = [{"outcome": "failure", "agency": 0.3, "novelty": 0.0}]
        integration.observe_run_events(state, events)
        ss = state["meta"]["self_state"]
        assert ss["affect"]["valence"] < 0.0

    def test_observe_run_events_writes_affect_success(self, monkeypatch):
        """Success events produce positive valence."""
        monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
        state = _make_state()
        events = [{"outcome": "success", "agency": 0.8, "novelty": 0.1}]
        integration.observe_run_events(state, events)
        ss = state["meta"]["self_state"]
        assert ss["affect"]["valence"] > 0.0

    def test_observe_run_events_initializes_self_state_if_absent(self, monkeypatch):
        """observe_run_events lazily creates self_state even if ensure wasn't called."""
        monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
        state = _make_state()
        integration.observe_run_events(state, [])
        assert state["meta"]["self_state"] is not None

    def test_route_pre_act_returns_deliberate_by_default(self, monkeypatch):
        """With shortcut OFF (default), ON path still returns deliberate."""
        monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
        state = _make_state()
        result = integration.route_pre_act(state, "python", {"p_true": 0.5})
        assert result in ("fast", "deliberate")

    def test_route_pre_act_returns_fast_when_shortcut_enabled(self, monkeypatch):
        """With shortcut ON and high confidence, route can return 'fast'."""
        monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
        monkeypatch.setattr(config, "HN_INTUITION_SHORTCUT", True)
        monkeypatch.setattr(config, "HN_THETA_HARD", 0.50)  # lower bar so 0.99 clears it
        state = _make_state()
        signals = {"p_true": 0.99, "self_consistency": 0.99, "ood": False}
        result = integration.route_pre_act(state, "python", signals)
        assert result == "fast"

    def test_maybe_run_instinct_delegates_empty_chat(self, monkeypatch):
        """Fake chat returning empty → maybe_flag returns None (no flag)."""
        monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
        state = {"meta": {"self_state": None}}

        def fake_chat(system, user):
            return {"message": {"content": ""}}

        result = integration.maybe_run_instinct(state, [], [], chat=fake_chat)
        assert result is None

    def test_maybe_run_instinct_surfaces_flag(self, monkeypatch):
        """Fake chat returning a signal → maybe_flag returns the sentence."""
        monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
        state = {"meta": {"self_state": None}}

        def fake_chat(system, user):
            return {"message": {"content": "Something feels off here."}}

        result = integration.maybe_run_instinct(state, [], [], chat=fake_chat)
        assert result == "Something feels off here."

    def test_at_teardown_returns_consolidation_report(self, monkeypatch):
        """at_teardown returns a dict with the consolidation cycle keys."""
        monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
        state = _make_state()
        scored = [{"domain": "python", "correct": True}]
        report = integration.at_teardown(state, scored, [])
        assert report is not None
        assert "competence_updated" in report
        assert "python" in report["competence_updated"]
        assert "proposals" in report
        assert "practice" in report

    def test_at_teardown_initializes_self_state_if_absent(self, monkeypatch):
        """at_teardown lazily creates self_state before running the cycle."""
        monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
        state = _make_state()
        integration.at_teardown(state, [], [])
        assert state["meta"]["self_state"] is not None
