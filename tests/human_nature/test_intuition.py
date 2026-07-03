"""Tests for human_nature/intuition.py (Phase 3.3).

Covers:
- snap() signal fusion, vibe labels, OOD flag propagation
- recalibration applied to fused p
- route() dual-process gating: shortcut OFF by default (F-default-OFF guard)
"""
from __future__ import annotations

import config
from human_nature.conviction import recalibrate
from human_nature.intuition import route, snap


# ---------------------------------------------------------------------------
# snap — signal fusion
# ---------------------------------------------------------------------------

def test_snap_returns_expected_keys():
    result = snap("backend", {})
    assert "p" in result
    assert "vibe" in result
    assert "ood" in result


def test_snap_no_signals_defaults_half():
    """No numeric signals → fused mean = 0.5 → recalibrate(0.5, 2.5) == 0.5."""
    result = snap("backend", {})
    assert abs(result["p"] - 0.5) < 1e-9


def test_snap_high_p_vibe():
    result = snap("backend", {"p_true": 0.95, "self_consistency": 0.9})
    assert result["vibe"] == "this'll pass"


def test_snap_low_p_vibe():
    result = snap("backend", {"p_true": 0.1, "self_consistency": 0.2})
    assert result["vibe"] == "something's off"


def test_snap_ood_propagated_true():
    result = snap("backend", {"p_true": 0.9, "ood": True})
    assert result["ood"] is True


def test_snap_ood_defaults_false():
    result = snap("backend", {"p_true": 0.9})
    assert result["ood"] is False


def test_snap_p_is_recalibrated():
    """Fused p must equal recalibrate(raw_mean) — not the raw mean itself."""
    signals = {"p_true": 0.95, "self_consistency": 0.95, "similarity": 0.95}
    raw_mean = 0.95
    expected = recalibrate(raw_mean, config.HN_RECAL_TEMPERATURE)
    result = snap("domain", signals)
    assert abs(result["p"] - expected) < 1e-9
    assert result["p"] != raw_mean  # recalibration actually changed the value


def test_snap_fuses_only_present_numeric_keys():
    """Only p_true, self_consistency, similarity contribute; 'ood' is boolean only."""
    # p_true=0.8 only → raw mean = 0.8
    result = snap("x", {"p_true": 0.8, "ood": False})
    expected = recalibrate(0.8, config.HN_RECAL_TEMPERATURE)
    assert abs(result["p"] - expected) < 1e-9


def test_snap_similarity_included_in_fusion():
    """similarity is a valid numeric signal."""
    result = snap("x", {"similarity": 0.7})
    expected = recalibrate(0.7, config.HN_RECAL_TEMPERATURE)
    assert abs(result["p"] - expected) < 1e-9


# ---------------------------------------------------------------------------
# route — dual-process routing
# ---------------------------------------------------------------------------

def test_route_default_shortcut_off_always_deliberate(monkeypatch):
    """HN_INTUITION_SHORTCUT defaults False → deliberate regardless of p or ood.

    Coded default, not the live env -- a real install may have flipped this
    flag on for dogfooding, so pin it off here regardless."""
    monkeypatch.setattr(config, "HN_INTUITION_SHORTCUT", False)
    s = snap("backend", {"p_true": 0.99, "self_consistency": 0.99, "similarity": 0.99})
    # Don't pass shortcut_enabled → falls back to config (False)
    assert route(s) == "deliberate"


def test_route_ood_forces_deliberate_even_with_shortcut():
    """OOD → always deliberate; uncertainty about distribution outweighs confidence."""
    s = snap("backend", {"p_true": 0.99, "self_consistency": 0.99, "ood": True})
    assert route(s, shortcut_enabled=True) == "deliberate"


def test_route_low_p_forces_deliberate_with_shortcut():
    """Low confidence → deliberate even when shortcut enabled."""
    s = snap("backend", {"p_true": 0.1, "self_consistency": 0.1})
    assert route(s, shortcut_enabled=True) == "deliberate"


def test_route_shortcut_true_high_p_not_ood_is_fast():
    """Only case for 'fast': shortcut=True AND p >= HN_THETA_HARD AND not OOD."""
    # 0.99 signals → recalibrate(0.99, 2.5) ≈ 0.863 > 0.85 = HN_THETA_HARD
    s = snap("backend", {"p_true": 0.99, "self_consistency": 0.99, "similarity": 0.99})
    assert s["p"] >= config.HN_THETA_HARD, (
        f"Need p >= {config.HN_THETA_HARD} for fast path; got {s['p']}"
    )
    assert not s["ood"]
    assert route(s, shortcut_enabled=True) == "fast"


def test_route_explicit_shortcut_false_deliberate():
    """Passing shortcut_enabled=False always yields deliberate."""
    s = snap("backend", {"p_true": 0.99, "self_consistency": 0.99, "similarity": 0.99})
    assert route(s, shortcut_enabled=False) == "deliberate"


def test_route_shortcut_true_borderline_p_just_above_hard():
    """p exactly at HN_THETA_HARD qualifies for fast path."""
    # Build a snap with p == HN_THETA_HARD by finding the raw value whose
    # recalibration lands at the threshold.  Easier: just patch snap result.
    s = {"p": config.HN_THETA_HARD, "vibe": "this'll pass", "ood": False}
    assert route(s, shortcut_enabled=True) == "fast"


def test_route_shortcut_true_p_just_below_hard_deliberate():
    """p just below HN_THETA_HARD → deliberate even with shortcut."""
    s = {"p": config.HN_THETA_HARD - 0.001, "vibe": "this'll pass", "ood": False}
    assert route(s, shortcut_enabled=True) == "deliberate"
