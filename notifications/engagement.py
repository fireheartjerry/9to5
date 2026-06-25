"""Native engagement APIs (Tier 4) -- pure builders + mappers, no network, no discord.py.

  * ``gatePollPayload(gate)`` -- the Discord Poll object for a gated approval
    ("Approve this <gate>?  Yes / Revise / Abort").
  * ``voteToVerdict(answer)`` -- map a poll answer label to a ControlBus verdict
    (approve / reject), so the gateway's on_raw_poll_vote_add can resolve the gate.
  * ``scheduledEventPayload(...)`` -- the body for a guild Scheduled Event covering
    the 9-5 run window.

The transport (``discord_bot.createPoll`` / the gateway poll-vote listener) is thin
over these; the decision logic lives here where it is unit-testable.
"""
from __future__ import annotations

from typing import Optional

# Canonical gate-poll answers. Order matters (Discord answer_ids are 1-based by order).
GATE_ANSWERS = ("Yes", "Revise", "Abort")

_APPROVE = {"yes", "approve", "approved", "lgtm", "ship", "ok"}
_REJECT = {"revise", "reject", "rejected", "abort", "no", "deny", "stop"}


def voteToVerdict(answer: str) -> Optional[str]:
    """Map a poll answer label (e.g. 'Yes') to 'approve' | 'reject' | None."""
    t = "".join(ch for ch in (answer or "").lower() if ch.isalnum() or ch.isspace()).strip()
    for w in t.split():
        if w in _APPROVE:
            return "approve"
        if w in _REJECT:
            return "reject"
    return None


def gatePollPayload(gate: str, *, duration_hours: int = 1) -> dict:
    """A Discord Poll object asking the owner to resolve ``gate``. multiselect off; short window."""
    return {
        "question": {"text": f"Approve this {gate}?"[:300]},
        "answers": [{"poll_media": {"text": a}} for a in GATE_ANSWERS],
        "duration": max(1, min(int(duration_hours), 768)),   # Discord allows 1h..32d
        "allow_multiselect": False,
    }


def scheduledEventPayload(name: str, start_iso: str, end_iso: str,
                          description: str = "") -> dict:
    """Body for POST /guilds/{id}/scheduled-events -- an EXTERNAL event for the run window."""
    return {
        "name": name[:100],
        "privacy_level": 2,                 # GUILD_ONLY
        "entity_type": 3,                   # EXTERNAL
        "scheduled_start_time": start_iso,
        "scheduled_end_time": end_iso,
        "entity_metadata": {"location": "9to5 orchestrator"},
        "description": (description or "")[:1000],
    }
