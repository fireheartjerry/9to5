"""Tests for Phase 5.2 — Psyche surface (PRISM-gated interior readouts).

Covers render_discord and render_web; asserts that the PRISM gate blocks
accuracy-critical surfaces and that both renderers tolerate a minimal/empty
self_state without crashing.
"""
from __future__ import annotations

import pytest
from human_nature.self_state import new_self_state, set_affect
from human_nature.psyche_surface import render_discord, render_web


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _populated_ss() -> dict:
    ss = new_self_state()
    set_affect(ss, 0.5, 0.3, 0.8)
    ss["morale"] = 0.4
    ss["dissonance"] = 0.15
    ss["competence"]["async_bugs"] = {"p": 0.8, "n": 10}
    ss["attention_focus"] = "race condition in executor"
    ss["charter_version"] = "1.2"
    return ss


# ---------------------------------------------------------------------------
# render_discord — happy path
# ---------------------------------------------------------------------------

def test_render_discord_returns_dict():
    result = render_discord(_populated_ss())
    assert result is not None
    assert isinstance(result, dict)


def test_render_discord_has_title():
    result = render_discord(_populated_ss())
    assert "title" in result
    assert result["title"]


def test_render_discord_has_fields_list():
    result = render_discord(_populated_ss())
    assert "fields" in result
    assert isinstance(result["fields"], list)
    assert len(result["fields"]) > 0


def test_render_discord_fields_have_name_and_value():
    result = render_discord(_populated_ss())
    for field in result["fields"]:
        assert "name" in field
        assert "value" in field


def test_render_discord_competence_section_present():
    result = render_discord(_populated_ss())
    names_blob = " ".join(f["name"] for f in result["fields"]).lower()
    assert "competence" in names_blob or "capability" in names_blob


def test_render_discord_mood_section_present():
    result = render_discord(_populated_ss())
    names_blob = " ".join(f["name"] for f in result["fields"]).lower()
    assert "mood" in names_blob or "affect" in names_blob


def test_render_discord_dissonance_section_present():
    result = render_discord(_populated_ss())
    names_blob = " ".join(f["name"] for f in result["fields"]).lower()
    assert "dissonance" in names_blob


def test_render_discord_attention_focus_section_present():
    result = render_discord(_populated_ss())
    names_blob = " ".join(f["name"] for f in result["fields"]).lower()
    assert "attention" in names_blob


def test_render_discord_charter_section_present():
    result = render_discord(_populated_ss())
    names_blob = " ".join(f["name"] for f in result["fields"]).lower()
    assert "charter" in names_blob


# ---------------------------------------------------------------------------
# render_discord — PRISM gate
# ---------------------------------------------------------------------------

def test_render_discord_blocks_verifier():
    assert render_discord(_populated_ss(), surface="verifier") is None


def test_render_discord_blocks_verdict():
    assert render_discord(_populated_ss(), surface="verdict") is None


def test_render_discord_blocks_test_judgment():
    assert render_discord(_populated_ss(), surface="test_judgment") is None


def test_render_discord_blocks_diff_correctness():
    assert render_discord(_populated_ss(), surface="diff_correctness") is None


def test_render_discord_allows_psyche_surface():
    assert render_discord(_populated_ss(), surface="psyche") is not None


def test_render_discord_allows_discord_surface():
    assert render_discord(_populated_ss(), surface="discord") is not None


# ---------------------------------------------------------------------------
# render_discord — empty / minimal self_state robustness
# ---------------------------------------------------------------------------

def test_render_discord_tolerates_empty_dict():
    result = render_discord({})
    assert result is not None
    assert isinstance(result, dict)
    assert "title" in result
    assert "fields" in result


def test_render_discord_tolerates_new_self_state():
    result = render_discord(new_self_state())
    assert result is not None
    assert isinstance(result, dict)


def test_render_discord_tolerates_missing_attention_focus():
    ss = new_self_state()
    # No attention_focus key → should still render without crashing
    result = render_discord(ss)
    assert result is not None


def test_render_discord_tolerates_missing_charter_version():
    ss = new_self_state()
    result = render_discord(ss)
    assert result is not None


# ---------------------------------------------------------------------------
# render_web — happy path
# ---------------------------------------------------------------------------

def test_render_web_returns_string():
    html = render_web(_populated_ss())
    assert isinstance(html, str)
    assert len(html) > 0


def test_render_web_is_wrapped_in_div():
    html = render_web(_populated_ss())
    assert "<div" in html


def test_render_web_has_psyche_class():
    html = render_web(_populated_ss())
    assert 'class="psyche"' in html or "class='psyche'" in html


def test_render_web_competence_section_present():
    html = render_web(_populated_ss()).lower()
    assert "competence" in html or "capability" in html


def test_render_web_mood_section_present():
    html = render_web(_populated_ss()).lower()
    assert "mood" in html or "affect" in html


def test_render_web_dissonance_section_present():
    html = render_web(_populated_ss()).lower()
    assert "dissonance" in html


# ---------------------------------------------------------------------------
# render_web — robustness
# ---------------------------------------------------------------------------

def test_render_web_tolerates_empty_dict():
    html = render_web({})
    assert isinstance(html, str)
    assert len(html) > 0


def test_render_web_tolerates_new_self_state():
    html = render_web(new_self_state())
    assert isinstance(html, str)
    assert len(html) > 0


# ---------------------------------------------------------------------------
# Gap 1 — boredom label reachable via surface
# ---------------------------------------------------------------------------

def test_render_discord_boredom_label():
    """Low arousal + neutral valence yields boredom in Mood-Core field."""
    ss = new_self_state()
    set_affect(ss, 0.0, 0.1, 0.5)
    result = render_discord(ss)
    assert result is not None
    mood_values = [f["value"] for f in result["fields"] if "Mood" in f.get("name", "")]
    assert any("boredom" in v for v in mood_values)


def test_render_web_boredom_label():
    """Low arousal + neutral valence yields boredom in web render."""
    ss = new_self_state()
    set_affect(ss, 0.0, 0.1, 0.5)
    html = render_web(ss)
    assert "boredom" in html


# ---------------------------------------------------------------------------
# Gap 2 — autonomy curve on psyche surface
# ---------------------------------------------------------------------------

def test_render_discord_autonomy_with_domains():
    """render_discord with autonomy dict must include the ceiling tiers."""
    result = render_discord(_populated_ss(), autonomy={"async": "hard", "windows": "soft"})
    assert result is not None
    values_blob = " ".join(f["value"] for f in result["fields"])
    assert "hard" in values_blob
    assert "soft" in values_blob


def test_render_discord_autonomy_placeholder_when_none():
    """render_discord with autonomy=None must show the earning trust placeholder."""
    result = render_discord(_populated_ss())  # autonomy defaults to None
    assert result is not None
    values_blob = " ".join(f["value"] for f in result["fields"])
    assert "earning trust" in values_blob


def test_render_discord_autonomy_field_present():
    """An Autonomy field must always appear in the embed."""
    result = render_discord(_populated_ss())
    assert result is not None
    names = [f["name"] for f in result["fields"]]
    assert "Autonomy" in names


def test_render_discord_existing_callers_unaffected():
    """Calling render_discord without autonomy arg must still succeed."""
    result = render_discord(_populated_ss(), surface="psyche")
    assert result is not None
    assert isinstance(result["fields"], list)


def test_render_web_autonomy_with_domains():
    """render_web with autonomy dict must include the ceiling tiers."""
    html = render_web(_populated_ss(), autonomy={"async": "hard", "windows": "soft"})
    assert "hard" in html
    assert "soft" in html


def test_render_web_autonomy_placeholder_when_none():
    """render_web with autonomy=None must show the earning trust placeholder."""
    html = render_web(_populated_ss())  # autonomy defaults to None
    assert "earning trust" in html


def test_render_web_existing_callers_unaffected():
    """Calling render_web without autonomy arg must still return valid HTML."""
    html = render_web(new_self_state())
    assert "<div" in html
    assert "psyche" in html
