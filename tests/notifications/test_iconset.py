"""Tests for Discord icon rendering fallback behavior."""
from __future__ import annotations

from notifications import iconset


def test_render_icon_returns_none_for_unknown_concept(monkeypatch):
    monkeypatch.setattr(iconset.theme, "iconChar", lambda concept: "")

    assert iconset.renderIcon("unknown") is None
