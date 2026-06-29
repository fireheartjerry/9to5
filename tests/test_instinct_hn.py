"""Tests for human_nature/instinct.py (Phase 3.4).

Tests cover:
- empty/whitespace model reply → None (no flag)
- non-empty reply → flag returned + appended to instinct_flags + conviction recorded
- second call same run → None (once-per-run guard; chat call-count stays at 1)
- works when notifications.instinct (Spec-B) is absent (default on this branch)
- db_path isolation (uses tmp_path)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from memory.conviction_ledger import track_record
from human_nature.instinct import maybe_flag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chat(reply: str):
    """Fake chat that records call count and returns a response dict."""
    calls: list[int] = [0]

    def _chat(system: str, user: str):  # noqa: ARG001
        calls[0] += 1
        return {"message": {"content": reply}}

    _chat.calls = calls  # type: ignore[attr-defined]
    return _chat


def _fresh_state(domain: str = "general") -> dict:
    return {"meta": {"goal_raw": "test task", "domain": domain}}


# ---------------------------------------------------------------------------
# empty/whitespace reply → None
# ---------------------------------------------------------------------------

def test_empty_reply_returns_none(tmp_path: Path):
    chat = _make_chat("")
    state = _fresh_state()
    result = maybe_flag(state, [], [], chat=chat, db_path=tmp_path / "c.db")
    assert result is None


def test_whitespace_reply_returns_none(tmp_path: Path):
    chat = _make_chat("   \n  ")
    state = _fresh_state()
    result = maybe_flag(state, [], [], chat=chat, db_path=tmp_path / "c.db")
    assert result is None


# ---------------------------------------------------------------------------
# non-empty reply → flag + ledger entry
# ---------------------------------------------------------------------------

def test_non_empty_reply_returns_flag_text(tmp_path: Path):
    chat = _make_chat("Something feels off with the retry loop.")
    state = _fresh_state()
    result = maybe_flag(state, [], [], chat=chat, db_path=tmp_path / "c.db")
    assert result == "Something feels off with the retry loop."


def test_flag_appended_to_instinct_flags(tmp_path: Path):
    chat = _make_chat("Race condition smell.")
    state = _fresh_state()
    maybe_flag(state, [], [], chat=chat, db_path=tmp_path / "c.db")
    flags = state["meta"]["instinct_flags"]
    assert len(flags) == 1
    assert "Race condition smell." in flags[0]


def test_flag_records_judgment_in_ledger(tmp_path: Path):
    db = tmp_path / "c.db"
    state = {"meta": {"instinct_flags": [], "goal_raw": "x"}}
    chat = lambda *a, **k: {"message": {"content": "something feels off about the pool"}}  # noqa: E731
    out = maybe_flag(state, [], [], chat=chat, db_path=db)
    assert out  # non-empty flag returned
    rows = sqlite3.connect(str(db)).execute(
        "SELECT COUNT(*) FROM judgments WHERE judgment_type='instinct'"
    ).fetchone()[0]
    assert rows == 1


def test_flag_records_judgment_with_general_domain(tmp_path: Path):
    """State without explicit domain falls back to 'general' for the ledger entry."""
    db = tmp_path / "c.db"
    chat = _make_chat("Something smells off.")
    state = {"meta": {"goal_raw": "do stuff"}}  # no explicit domain key
    maybe_flag(state, [], [], chat=chat, db_path=db)
    # Side effect: instinct_flags populated
    assert len(state["meta"]["instinct_flags"]) == 1


# ---------------------------------------------------------------------------
# once-per-run guard
# ---------------------------------------------------------------------------

def test_second_call_same_run_returns_none(tmp_path: Path):
    chat = _make_chat("Something feels off.")
    state = _fresh_state()
    first = maybe_flag(state, [], [], chat=chat, db_path=tmp_path / "c.db")
    second = maybe_flag(state, [], [], chat=chat, db_path=tmp_path / "c.db")
    assert first is not None   # first call worked
    assert second is None       # second call blocked by once-per-run guard


def test_second_call_does_not_call_chat_again(tmp_path: Path):
    """Chat callable must be invoked exactly once; second call is suppressed."""
    chat = _make_chat("Feels wrong.")
    state = _fresh_state()
    maybe_flag(state, [], [], chat=chat, db_path=tmp_path / "c.db")
    maybe_flag(state, [], [], chat=chat, db_path=tmp_path / "c.db")
    assert chat.calls[0] == 1, (
        f"Expected exactly 1 chat call; got {chat.calls[0]}"
    )


# ---------------------------------------------------------------------------
# plain dict state (no pre-existing meta)
# ---------------------------------------------------------------------------

def test_works_with_empty_plain_dict_state(tmp_path: Path):
    chat = _make_chat("Possible deadlock pattern.")
    state: dict = {}
    result = maybe_flag(state, [], [], chat=chat, db_path=tmp_path / "c.db")
    assert result == "Possible deadlock pattern."
    assert "instinct_flags" in state["meta"]


# ---------------------------------------------------------------------------
# _nc (notifications.instinct Spec-B) absent — graceful degradation
# ---------------------------------------------------------------------------

def test_operates_standalone_when_spec_b_absent(tmp_path: Path, monkeypatch):
    """maybe_flag must work when notifications.instinct is absent (default on this branch)."""
    import human_nature.instinct as _mod
    # Force _nc to None as it would be when Spec-B is not installed
    monkeypatch.setattr(_mod, "_nc", None)
    chat = _make_chat("Pattern recognition signal.")
    state = _fresh_state()
    result = maybe_flag(state, [], [], chat=chat, db_path=tmp_path / "c.db")
    assert result == "Pattern recognition signal."


# ---------------------------------------------------------------------------
# reflections / failure_modes fed into prompt (smoke check)
# ---------------------------------------------------------------------------

def test_reflections_and_failure_modes_accepted(tmp_path: Path):
    chat = _make_chat("Something feels wrong here.")
    state = _fresh_state()
    reflections = [{"approach": "retry with backoff"}, {"approach": "early exit"}]
    failure_modes = [{"taxonomy_class": "timeout", "root_cause": "slow network"}]
    result = maybe_flag(state, reflections, failure_modes, chat=chat, db_path=tmp_path / "c.db")
    assert result == "Something feels wrong here."
