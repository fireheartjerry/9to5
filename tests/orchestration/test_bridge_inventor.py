"""Tests for platform_core/orchestration/human_nature_bridge/inventor.py.

THE REGRESSION GUARANTEE: the inventor engine is dark in this checkout (uncommitted /
package absent) and gated behind three flags (HUMAN_NATURE_ENABLED, HN_INVENTOR_COUPLING,
INVENTOR_MODE_ENABLED). inventorCouple must be a clean no-op -- return None, never raise
ImportError, never touch state.meta -- whenever any gate is off OR the inventor package
cannot be imported.
"""

from __future__ import annotations

import sys
import types

import config

from platform_core.orchestration.human_nature_bridge import inventor as hn_inventor


def _make_state() -> dict:
    return {"meta": {}}


def test_inventor_couple_noop_when_all_flags_default(monkeypatch):
    """Default checkout: INVENTOR_MODE_ENABLED is False -> clean no-op, no import attempted."""
    state = _make_state()
    assert hn_inventor.inventorCouple(state) is None
    assert "hn_inventor" not in state["meta"]


def test_inventor_couple_noop_when_human_nature_disabled(monkeypatch):
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", False)
    monkeypatch.setattr(config, "HN_INVENTOR_COUPLING", True)
    monkeypatch.setattr(config, "INVENTOR_MODE_ENABLED", True)
    state = _make_state()
    assert hn_inventor.inventorCouple(state) is None
    assert "hn_inventor" not in state["meta"]


def test_inventor_couple_noop_when_hn_inventor_coupling_disabled(monkeypatch):
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INVENTOR_COUPLING", False)
    monkeypatch.setattr(config, "INVENTOR_MODE_ENABLED", True)
    state = _make_state()
    assert hn_inventor.inventorCouple(state) is None
    assert "hn_inventor" not in state["meta"]


def test_inventor_couple_noop_when_inventor_mode_disabled(monkeypatch):
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INVENTOR_COUPLING", True)
    monkeypatch.setattr(config, "INVENTOR_MODE_ENABLED", False)
    state = _make_state()
    assert hn_inventor.inventorCouple(state) is None
    assert "hn_inventor" not in state["meta"]


def test_inventor_couple_gracefully_noop_when_package_not_importable(monkeypatch):
    """All three gates ON but the inventor package is absent from this checkout -- must
    return None without raising ImportError, and must not touch state.meta."""
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INVENTOR_COUPLING", True)
    monkeypatch.setattr(config, "INVENTOR_MODE_ENABLED", True)
    state = _make_state()
    result = hn_inventor.inventorCouple(state)  # must not raise
    assert result is None
    assert "hn_inventor" not in state["meta"]


def test_inventor_couple_gracefully_noop_with_dashboard_when_package_not_importable(monkeypatch):
    """Same as above but with a dashboard passed -- must not touch it either."""
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INVENTOR_COUPLING", True)
    monkeypatch.setattr(config, "INVENTOR_MODE_ENABLED", True)
    events = []

    class _Dash:
        def event(self, msg):
            events.append(msg)

    state = _make_state()
    result = hn_inventor.inventorCouple(state, _Dash())
    assert result is None
    assert events == []
    assert "hn_inventor" not in state["meta"]


def test_inventor_couple_never_raises_on_malformed_state(monkeypatch):
    """Best-effort: gated off by default, so even a malformed state is a clean no-op."""
    state = {"meta": {}}
    assert hn_inventor.inventorCouple(state) is None


def test_inventor_couple_duplicate_knobs_are_idempotent(monkeypatch):
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INVENTOR_COUPLING", True)
    monkeypatch.setattr(config, "INVENTOR_MODE_ENABLED", True)
    monkeypatch.setitem(sys.modules, "inventor", types.ModuleType("inventor"))
    state = {"meta": {"self_state": {}}}

    first = hn_inventor.inventorCouple(state)
    second = hn_inventor.inventorCouple(state)

    assert second == first
    assert state["meta"]["hn_inventor"] == [first]
