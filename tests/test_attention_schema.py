"""Tests for human_nature.attention_schema — Attention Schema (AST).

All tests are pure/offline. Intensity model: each update() with a DIFFERENT
content multiplies current intensity by DECAY (floored at 0.0); re-attending
the same content refreshes intensity to 1.0; first update starts at 1.0.
"""
from __future__ import annotations


def _winner(content: str, salience: float = 0.8) -> dict:
    """Build a minimal broadcast-winner dict."""
    return {"winner": "spec", "content": content, "salience": salience, "losers": []}


# ---------------------------------------------------------------------------
# Neutral empty state before any update
# ---------------------------------------------------------------------------

def test_initial_focus_is_neutral():
    from human_nature.attention_schema import AttentionSchema

    ast = AttentionSchema()
    f = ast.focus()
    assert f["attending"] == ""
    assert f["intensity"] == 0.0
    assert f["faded"] == []


# ---------------------------------------------------------------------------
# update() and focus()
# ---------------------------------------------------------------------------

def test_focus_reflects_last_winner():
    from human_nature.attention_schema import AttentionSchema

    ast = AttentionSchema()
    ast.update(_winner("race condition"))
    f = ast.focus()
    assert f["attending"] == "race condition"
    assert f["intensity"] == 1.0
    assert f["faded"] == []


def test_displaced_content_enters_faded():
    from human_nature.attention_schema import AttentionSchema

    ast = AttentionSchema()
    ast.update(_winner("alpha"))
    ast.update(_winner("beta"))
    f = ast.focus()
    assert f["attending"] == "beta"
    assert "alpha" in f["faded"]


def test_faded_accumulates_in_displacement_order():
    from human_nature.attention_schema import AttentionSchema

    ast = AttentionSchema()
    for label in ["a", "b", "c", "d"]:
        ast.update(_winner(label))
    f = ast.focus()
    assert f["attending"] == "d"
    assert f["faded"] == ["a", "b", "c"]


def test_faded_list_is_bounded_by_cap():
    from human_nature.attention_schema import AttentionSchema, FADED_CAP

    ast = AttentionSchema()
    for i in range(FADED_CAP + 5):
        ast.update(_winner(f"item-{i}"))
    f = ast.focus()
    assert len(f["faded"]) <= FADED_CAP


# ---------------------------------------------------------------------------
# Intensity decay and refresh
# ---------------------------------------------------------------------------

def test_intensity_one_on_first_update():
    from human_nature.attention_schema import AttentionSchema

    ast = AttentionSchema()
    ast.update(_winner("hello"))
    assert ast.focus()["intensity"] == 1.0


def test_intensity_decays_on_successive_different_updates():
    from human_nature.attention_schema import AttentionSchema, DECAY

    ast = AttentionSchema()
    ast.update(_winner("first"))   # intensity = 1.0
    ast.update(_winner("second"))  # different: intensity = 1.0 * DECAY
    ast.update(_winner("third"))   # different: intensity = DECAY * DECAY
    f = ast.focus()
    assert f["attending"] == "third"
    assert abs(f["intensity"] - DECAY ** 2) < 1e-9


def test_reattending_same_content_refreshes_to_one():
    from human_nature.attention_schema import AttentionSchema, DECAY

    ast = AttentionSchema()
    ast.update(_winner("topic"))   # intensity = 1.0
    ast.update(_winner("other"))   # different: intensity = DECAY
    ast.update(_winner("topic"))   # re-attending "topic": refresh to 1.0
    f = ast.focus()
    assert f["attending"] == "topic"
    assert f["intensity"] == 1.0


def test_intensity_floored_at_zero():
    from human_nature.attention_schema import AttentionSchema

    ast = AttentionSchema()
    ast.update(_winner("seed"))
    for i in range(100):           # drive decay to floor
        ast.update(_winner(f"item-{i}"))
    assert ast.focus()["intensity"] >= 0.0
