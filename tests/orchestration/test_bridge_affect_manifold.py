"""Tests for the manifold-aware emotion label coupling in
platform_core/orchestration/human_nature_bridge/affect.py.

Phase 1.3 (human-nature-psyche-v2): when config.HN_MANIFOLD is on, emotionAdvisory
must derive its emotion label from the continuous 9-axis affect_manifold (via
human_nature.prototypes.dominant) instead of the legacy PAD rule (_affectToLabel).
With HN_MANIFOLD off, behavior must stay byte-identical to the legacy path (A/B safe).
"""

from __future__ import annotations

import config
from platform_core.orchestration.human_nature_bridge.affect import (
    _affectToLabel,
    _emotionLabel,
)


def test_emotion_label_uses_legacy_pad_rule_when_manifold_off(monkeypatch):
    """HN_MANIFOLD off -> byte-identical to the legacy _affectToLabel(affect) rule."""
    monkeypatch.setattr(config, "HN_MANIFOLD", False)
    affect = {"valence": -0.7, "arousal": 0.7, "control": 0.0}
    self_state = {
        "affect": affect,
        "affect_manifold": {"valence": 0.7, "arousal": 0.2, "dominance": 0.4},  # ignored
    }
    assert _emotionLabel(self_state) == _affectToLabel(affect) == "frustration"


def test_emotion_label_uses_manifold_projection_when_on(monkeypatch):
    """HN_MANIFOLD on -> label comes from prototypes.dominant() over affect_manifold,
    NOT the legacy PAD affect (they are set to disagree so this is unambiguous)."""
    monkeypatch.setattr(config, "HN_MANIFOLD", True)
    self_state = {
        "affect": {"valence": 0.9, "arousal": 0.1, "control": 0.0},  # would be "satisfaction"
        "affect_manifold": {"valence": -0.6, "arousal": 0.6, "tension": 0.6},  # frustration anchor
    }
    assert _emotionLabel(self_state) == "frustration"


def test_emotion_label_manifold_falls_back_on_malformed_manifold(monkeypatch):
    """A garbage affect_manifold must never raise -- falls back to the legacy PAD rule."""
    monkeypatch.setattr(config, "HN_MANIFOLD", True)
    self_state = {
        "affect": {"valence": -0.7, "arousal": 0.0, "control": 0.0},  # legacy -> "anxiety"
        "affect_manifold": "not-a-dict",
    }
    assert _emotionLabel(self_state) == "anxiety"


def test_emotion_label_manifold_missing_defaults_to_empty(monkeypatch):
    """No affect_manifold key at all -> treated as {} -> prototypes.dominant({}) -> neutral."""
    monkeypatch.setattr(config, "HN_MANIFOLD", True)
    self_state = {"affect": {"valence": 0.9, "arousal": 0.1, "control": 0.0}}
    assert _emotionLabel(self_state) == "neutral"
