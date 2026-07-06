"""psyche_cog gateway shell: read-only psyche routers + bang dispatch (no live gateway).

Mirrors the existing cog-test patterns (log_cog/runs_cog): a tiny fake bot for
setup(), monkeypatched config gate, and direct calls on the pure render/dispatch
cores with fake/empty state. No live Discord gateway is touched.
"""
from __future__ import annotations

import asyncio

import config
from notifications import psyche_cog


class _Bot:
    def __init__(self) -> None:
        self.cogs = []

    async def add_cog(self, cog) -> None:
        self.cogs.append(cog)


def _on(monkeypatch) -> None:
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True, raising=False)


def _off(monkeypatch) -> None:
    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", False, raising=False)


# --- registration -----------------------------------------------------------

def test_setup_registers_psyche_cog():
    bot = _Bot()
    asyncio.run(psyche_cog.setup(bot))
    assert len(bot.cogs) == 1
    assert isinstance(bot.cogs[0], psyche_cog.PsycheCog)


def test_cog_exposes_expected_slash_commands():
    attrs = dir(psyche_cog.PsycheCog)
    for cmd in ("psyche", "dial", "charter", "why", "whatyouknow"):
        assert cmd in attrs


# --- each command invokes its router ----------------------------------------

def test_psyche_invokes_cmd_psyche(monkeypatch):
    _on(monkeypatch)
    seen = {}

    def fake_psyche(ss, autonomy=None):
        seen["hit"] = True
        return "PSYCHE"

    monkeypatch.setattr(psyche_cog, "cmd_psyche", fake_psyche)
    out = psyche_cog.renderPsyche(None)
    assert out == "PSYCHE" and seen["hit"]


def test_charter_invokes_cmd_charter(monkeypatch):
    _on(monkeypatch)
    monkeypatch.setattr(psyche_cog, "cmd_charter", lambda charter: "CHARTER")
    assert psyche_cog.renderCharter(None) == "CHARTER"


def test_whatyouknow_invokes_cmd_whatyouknow(monkeypatch):
    _on(monkeypatch)
    monkeypatch.setattr(psyche_cog, "cmd_whatyouknow", lambda um: "WHATYOUKNOW")
    assert psyche_cog.renderWhatYouKnow(None) == "WHATYOUKNOW"


def test_dial_no_arg_shows_current_dials(monkeypatch):
    _on(monkeypatch)
    out = psyche_cog.renderDial(None, "")
    assert isinstance(out, str) and out
    # shows a known trait from the character vector
    assert "honesty" in out.lower()


def test_dial_with_arg_proposes_not_applies(monkeypatch):
    _on(monkeypatch)
    called = {}
    monkeypatch.setattr(psyche_cog, "cmd_dial",
                        lambda vec, trait, value: (called.setdefault("v", (trait, value)) or vec,
                                                   f"dialed {trait}={value}"))
    out = psyche_cog.renderDial(None, "honesty 80")
    assert called["v"] == ("honesty", 80.0)
    # propose-not-apply: reply flags this as a proposal, never a persisted change
    assert "propos" in out.lower()


def test_why_invokes_router_and_reads_receipts(monkeypatch):
    _on(monkeypatch)
    monkeypatch.setattr(psyche_cog, "cmd_why_i_feel", lambda ss, av: "AFFECT-TRACE")
    meta = {"hn_votes": [{"domain": "tests", "tier": "vote", "flag": True}]}
    out = psyche_cog.renderWhy({"meta": meta})
    assert "AFFECT-TRACE" in out
    assert "tests" in out  # the authority-exercise receipt is surfaced


# --- HN-off path replies gracefully -----------------------------------------

def test_all_renderers_off_reply_gracefully(monkeypatch):
    _off(monkeypatch)
    for fn in (psyche_cog.renderPsyche, psyche_cog.renderCharter,
               psyche_cog.renderWhatYouKnow, psyche_cog.renderWhy):
        out = fn(None)
        assert isinstance(out, str) and "off" in out.lower()
    out = psyche_cog.renderDial(None, "honesty 80")
    assert isinstance(out, str) and "off" in out.lower()


def test_dispatch_off_replies_gracefully(monkeypatch):
    _off(monkeypatch)
    out = psyche_cog.dispatchPsyche("!psyche", state=None)
    assert isinstance(out, str) and "off" in out.lower()


# --- no command raises on empty / missing psyche state ----------------------

def test_renderers_never_raise_on_empty_state(monkeypatch):
    _on(monkeypatch)
    for state in (None, {}, {"meta": {}}):
        assert isinstance(psyche_cog.renderPsyche(state), str)
        assert isinstance(psyche_cog.renderCharter(state), str)
        assert isinstance(psyche_cog.renderWhatYouKnow(state), str)
        assert isinstance(psyche_cog.renderWhy(state), str)
        assert isinstance(psyche_cog.renderDial(state, ""), str)
        assert isinstance(psyche_cog.renderDial(state, "honesty 80"), str)


# --- dispatch routing -------------------------------------------------------

def test_dispatch_routes_each_bang(monkeypatch):
    _on(monkeypatch)
    for bang in ("!psyche", "!charter", "!whatyouknow", "!why"):
        out = psyche_cog.dispatchPsyche(bang, state=None)
        assert isinstance(out, str) and out
    assert psyche_cog.dispatchPsyche("!dial", state=None)


def test_dispatch_ignores_non_psyche_bang(monkeypatch):
    _on(monkeypatch)
    assert psyche_cog.dispatchPsyche("!status", state=None) is None
    assert psyche_cog.dispatchPsyche("hello", state=None) is None


def test_setup_is_callable():
    assert callable(psyche_cog.setup)
