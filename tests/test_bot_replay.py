"""Aggressive offline exercise of the Nightclaw '!' control surface via the bot-replay harness.

Every case asserts (a) NO unhandled exception escaped the command spine and (b) the correct
behaviour (authorization gating, dedup, cursor replay, REST safety). This is the safe substitute
for a second live gateway -- see docs/TESTING.md.

RUN/TEST: python -m pytest tests/test_bot_replay.py -q
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import config
from notifications import commands as spine
from notifications import discord_client as _dc
from platform_core.simulator import bot_replay as br


# --------------------------------------------------------------------------- helpers
def _fresh(**kw) -> br.BotReplay:
    br.resetTransport()
    return br.BotReplay(**kw)


def _no_errors(r: br.ReplayResult) -> None:
    assert r.errors == [], f"unhandled exceptions escaped the spine: {r.errors}"


# --------------------------------------------------------------------------- every '!' command
@pytest.mark.parametrize("name,meta", sorted(spine.COMMAND_REGISTRY.items()))
def test_every_command_no_crash(name, meta):
    """Fire every registered command with a plausible arg; nothing may raise, a reply must come."""
    arg = ""
    if meta["arg"] == "required":
        arg = {"skip": " st-002", "set-effort": " st-002 high", "effort": " high",
               "mode": " watch", "deadline": " +1h", "prefer": " brief",
               "intent": " go faster", "inject": " extra ctx"}.get(name, " st-002")
    h = _fresh(pending_gate="plan")
    h.enqueueCommand(f"!{name}{arg}")
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert r.applied == [(br.GATEWAY, name)]


def test_all_commands_sequential_single_harness():
    """Blast the whole registry through one harness back-to-back -- no cross-command corruption."""
    h = _fresh(pending_gate="plan")
    for name, meta in spine.COMMAND_REGISTRY.items():
        arg = " st-002 high" if name == "set-effort" else (" st-002" if meta["arg"] != "none" else "")
        h.enqueueCommand(f"!{name}{arg}")
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert len(r.applied) == len(spine.COMMAND_REGISTRY)


# --------------------------------------------------------------------------- malformed args
@pytest.mark.parametrize("text", [
    "!skip", "!skip garbage", "!skip st-9", "!skip st-99999",
    "!add", "!add    ", "!set-effort st-002", "!set-effort st-002 bogus",
    "!set-effort notanid high", "!effort", "!effort turbo", "!mode", "!mode sideways",
    "!deadline", "!deadline soon", "!deadline +", "!intent", "!prefer",
    "!inject", "!", "!   ", "!STATUS", "!Abort",
])
def test_malformed_args_never_crash(text):
    h = _fresh()
    h.enqueueCommand(text)
    r = h.run(br.GATEWAY)
    _no_errors(r)


def test_unknown_command_ignored_no_op():
    h = _fresh()
    mid = h.enqueueCommand("!frobnicate the gizmo")
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert r.applied == []
    assert (mid, "unknown_command") in r.ignored


# --------------------------------------------------------------------------- authorization gating
def test_unauthorized_sender_rejected():
    h = _fresh()
    mid = h.enqueueCommand("!abort", authorized=False)
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert r.applied == []
    assert (mid, "unauthorized") in r.ignored
    assert not h.bus.isAbort()


def test_bot_author_ignored():
    h = _fresh()
    mid = h.enqueueCommand("!abort", is_bot=True)
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert r.applied == []
    assert (mid, "bot_author") in r.ignored
    assert not h.bus.isAbort()


def test_configured_owner_blocks_stranger(monkeypatch):
    """With a real owner snowflake configured, a stranger's id is rejected by spine.isAuthorized."""
    monkeypatch.setattr(config, "DISCORD_HUMAN_USER_ID", "123456789012345678")
    h = _fresh()
    h.enqueueCommand("!abort", author_id=999, authorized=True)          # stranger
    h.enqueueCommand("!pause", author_id=123456789012345678, authorized=True)  # owner
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert r.applied == [(br.GATEWAY, "pause")]
    assert not h.bus.isAbort()
    assert h.bus.isPaused()


def test_wrong_channel_ignored(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_CHANNEL_ID", 555)
    h = _fresh(channel_id=555)
    mid = h.enqueueCommand("!abort", channel_id=111)
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert (mid, "wrong_channel") in r.ignored
    assert not h.bus.isAbort()


# --------------------------------------------------------------------------- duplicate / dedup
def test_duplicate_add_deduped():
    h = _fresh()
    h.enqueueCommand("!add build the widget")
    h.enqueueCommand("!add build the widget")
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert len(r.applied) == 2                       # both messages handled
    assert len(h.queuedOps()) == 1                   # but only ONE queued op survives dedup


def test_distinct_adds_not_deduped():
    h = _fresh()
    h.enqueueCommand("!add widget one")
    h.enqueueCommand("!add widget two")
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert len(h.queuedOps()) == 2


# --------------------------------------------------------------------------- pause / resume / abort races
def test_pause_resume_abort_sequence():
    h = _fresh()
    for c in ("!pause", "!resume", "!abort"):
        h.enqueueCommand(c)
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert not h.bus.isPaused()   # resume cleared the pause
    assert h.bus.isAbort()        # abort latched


def test_pause_then_abort_both_latch():
    h = _fresh()
    h.enqueueCommand("!pause")
    h.enqueueCommand("!abort")
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert h.bus.isPaused() and h.bus.isAbort()


def test_repeated_pause_resume_idempotent():
    h = _fresh()
    for c in ("!pause", "!pause", "!resume", "!resume"):
        h.enqueueCommand(c)
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert not h.bus.isPaused()


# --------------------------------------------------------------------------- gate decisions
def test_approve_reject_require_pending_gate():
    h = _fresh(pending_gate=None)
    h.enqueueCommand("!approve")
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert "No gate" in r.replies[0]


def test_approve_resolves_pending_gate():
    h = _fresh(pending_gate="plan")
    h.enqueueCommand("!approve")
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert h.bus.getDecision("plan") == "approve"


# --------------------------------------------------------------------------- oversized / unicode
def test_oversized_reply_clamped():
    h = _fresh()
    h.enqueueCommand("!add " + ("x" * 5000))
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert r.replies, "expected a reply for !add"
    assert all(len(reply) <= br.MAX_REPLY_CHARS for reply in r.replies)


def test_oversized_embed_clamped():
    """A realistic runaway embed (huge description + huge field values, the live-dashboard shape)
    is shrunk under Discord's 6000-char total by the value-shrinking loop, capped at 25 fields."""
    h = _fresh()
    embed = {"title": "T" * 80, "description": "D" * 9000,
             "fields": [{"name": f"field {i}", "value": "v" * 2000} for i in range(40)]}
    clamped = h.attemptEmbed(embed)
    assert _dc._embedLen(clamped) <= config.DISCORD_EMBED_TOTAL_MAX
    assert len(clamped["fields"]) <= 25
    assert all(len(f["value"]) <= config.DISCORD_MAX_FIELD_VALUE for f in clamped["fields"])
    assert len(clamped["description"]) <= config.DISCORD_MAX_EMBED_DESC


def test_embed_clamp_field_name_budget_is_enforced():
    """Regression for the former name-heavy budget gap: _clampEmbed now shrinks field NAMES (and, as a
    last resort, drops trailing fields) once value-shrinking is exhausted, so even 40 max-length names
    stay within Discord's 6000-char total instead of 400-ing the whole message."""
    h = _fresh()
    embed = {"title": "T" * 400, "description": "D" * 100,
             "fields": [{"name": "n" * 400, "value": "v" * 10} for _ in range(40)]}
    clamped = h.attemptEmbed(embed)
    assert len(clamped["fields"]) <= 25
    assert all(len(f["name"]) <= config.DISCORD_MAX_FIELD_NAME for f in clamped["fields"])
    assert len(clamped["title"]) <= config.DISCORD_MAX_EMBED_TITLE
    # The aggregate budget now holds even in the pathological name-heavy case:
    assert _dc._embedLen(clamped) <= config.DISCORD_EMBED_TOTAL_MAX


@pytest.mark.parametrize("garbage", [
    "!add \U0001f4a9​🌀 描述 \x00\x01 café",
    "!intent " + "‮" * 50,
    "!prefer 🤖 without cost",
    "!skip st-00﻿2",
])
def test_unicode_garbage_args_never_crash(garbage):
    h = _fresh()
    h.enqueueCommand(garbage)
    r = h.run(br.GATEWAY)
    _no_errors(r)


# --------------------------------------------------------------------------- cursor replay
def test_stale_abort_not_reapplied_via_cursor():
    """The poller advances its seen-cursor; a later message with a lower id is stale and skipped."""
    h = _fresh()
    h.enqueueCommand("!abort", msg_id=10)
    h.run(br.POLLER)
    assert h.bus.isAbort()
    applied_before = list(h.result.applied)
    # A stale (out-of-order, id below cursor) re-delivery of the same command:
    h.enqueueCommand("!abort", msg_id=5)
    h.run(br.POLLER)
    _no_errors(h.result)
    assert h.result.applied == applied_before, "stale message below cursor was re-applied"


def test_poller_advances_cursor_forward():
    h = _fresh()
    h.enqueueCommand("!add first", msg_id=1)
    h.run(br.POLLER)
    assert h.bus.getSeen() == "1"
    h.enqueueCommand("!add second", msg_id=7)
    h.run(br.POLLER)
    _no_errors(h.result)
    assert h.bus.getSeen() == "7"
    assert len(h.queuedOps()) == 2


# --------------------------------------------------------------------------- dual-consumer double-apply
def test_dual_consumer_op_applied_once():
    """A single Discord message is parsed by BOTH the gateway and the poller; pushOp dedup must
    collapse the doubly-pushed op to exactly one (no duplicate subtask)."""
    h = _fresh()
    h.enqueueCommand("!add shared subtask", msg_id=1)
    r = h.run(br.BOTH)
    _no_errors(r)
    consumers = {c for c, _ in r.applied}
    assert consumers == {br.GATEWAY, br.POLLER}      # both really applied
    assert len(h.queuedOps()) == 1                   # yet only one op survives


def test_dual_consumer_abort_idempotent():
    h = _fresh()
    h.enqueueCommand("!abort", msg_id=1)
    r = h.run(br.BOTH)
    _no_errors(r)
    assert h.bus.isAbort()


# --------------------------------------------------------------------------- REST 429 -> 401 safety
def test_simulated_429_then_401_no_op_no_crash(monkeypatch):
    """Drive the REAL chokepoint: a 429 arms the global breaker (next call no-ops without touching
    the network); a 401 latches the whole surface off. Neither raises."""
    br.resetTransport()
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(config, "DISCORD_CHANNEL_ID", 42)

    calls = {"n": 0}

    class _Resp:
        def __init__(self, code):
            self.status_code = code
            self.headers = {"Retry-After": "0"}
            self.text = ""

        def json(self):
            return {"retry_after": 0.0}

    def _fake_request(method, url, **kw):
        calls["n"] += 1
        return _Resp(429 if calls["n"] == 1 else 401)

    monkeypatch.setattr(_dc._SESSION, "request", _fake_request)
    h = br.BotReplay()
    # 1st send -> 429 arms the breaker; with retries=default the chokepoint sleeps(0) then retries
    # into the 401 on the same call, latching the surface off. Either way: no exception.
    first = h.attemptSend("hello")          # returns a Response (429/401), never raises
    assert first is not None
    net_after_first = calls["n"]
    # Surface now latched (401) -> every subsequent send short-circuits to None with NO network hit.
    second = h.attemptSend("again")
    assert second is None
    assert calls["n"] == net_after_first, "a latched/broken surface still hit the network"
    br.resetTransport()


def test_blank_token_send_is_noop():
    """Baseline offline invariant: with a blank token the chokepoint never touches the network."""
    br.resetTransport()
    h = br.BotReplay()
    assert h.attemptSend("anything") is None


# --------------------------------------------------------------------------- watchdog stale path
def test_watchdog_detects_stale_run():
    h = _fresh(status="running")
    old = (datetime.now(timezone.utc) - timedelta(seconds=5000)).isoformat()
    h.setLastActivity(old)
    now = datetime.now(timezone.utc).timestamp()
    assert h.isStale(now, threshold_s=600) is True


def test_watchdog_fresh_run_not_stale():
    h = _fresh(status="running")
    recent = datetime.now(timezone.utc).isoformat()
    h.setLastActivity(recent)
    assert h.isStale(datetime.now(timezone.utc).timestamp(), threshold_s=600) is False


def test_watchdog_terminal_run_never_stale():
    h = _fresh(status="done")
    old = (datetime.now(timezone.utc) - timedelta(seconds=5000)).isoformat()
    h.setLastActivity(old)
    assert h.isStale(datetime.now(timezone.utc).timestamp(), threshold_s=600) is False


# --------------------------------------------------------------------------- feedback capture (hermetic)
def test_control_commands_capture_feedback_labels():
    """approve/reject/skip/abort/retry/add record an implicit-feedback label -- captured in-memory,
    never written to the real SIE DB."""
    h = _fresh(pending_gate="plan")
    for c in ("!approve", "!abort", "!retry", "!add a thing"):
        h.enqueueCommand(c)
    r = h.run(br.GATEWAY)
    _no_errors(r)
    kinds = {fb["kind"] for fb in r.feedback}
    assert {"approve", "abort", "retry", "add"} <= kinds


# --------------------------------------------------------------------------- fully offline guarantee
def test_harness_makes_no_disk_or_network_side_effects():
    """The in-memory bus never creates a control file; sends no-op with the blank token."""
    h = _fresh()
    h.enqueueCommand("!add x")
    h.enqueueCommand("!pause")
    r = h.run(br.GATEWAY)
    _no_errors(r)
    assert h.bus.path is None
    assert config.DISCORD_BOT_TOKEN == ""   # conftest keeps it blank for the offline guarantee
