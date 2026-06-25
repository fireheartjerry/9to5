"""Tier 4 native engagement: resolve a gated approval from a native Poll vote.

When POLL_GATES is on and a gate is pending, the orchestrator posts a Poll
("Approve this <gate>? Yes / Revise / Abort"). This cog listens for the OWNER's vote
(on_raw_poll_vote_add), maps the answer to a verdict via the pure ``engagement`` mapper,
and resolves the gate through the ControlBus -- the same decision channel /approve uses,
so the orchestrator's existing gate-wait loop proceeds. Buttons + !approve remain the
fallback (they work even without the gateway running).
"""
from __future__ import annotations

import config
from control import ControlBus
from notifications import audit
from notifications import commands as spine
from notifications import engagement

from discord.ext import commands as dpy_commands

LOG = config.getLogger("cog.engagement")


def verdictForAnswer(answer_id) -> "str | None":
    """answer_id (1-based, in GATE_ANSWERS order) -> 'approve'|'reject'|None. Pure/testable."""
    if isinstance(answer_id, int) and 1 <= answer_id <= len(engagement.GATE_ANSWERS):
        return engagement.voteToVerdict(engagement.GATE_ANSWERS[answer_id - 1])
    return None


class EngagementCog(dpy_commands.Cog):
    def __init__(self, bot: dpy_commands.Bot) -> None:
        self.bot = bot

    @dpy_commands.Cog.listener()
    async def on_raw_poll_vote_add(self, payload) -> None:  # noqa: ANN001
        if not config.POLL_GATES:
            return
        owner = (config.DISCORD_HUMAN_USER_ID or "").strip()
        if owner.isdigit() and getattr(payload, "user_id", None) != int(owner):
            return
        verdict = verdictForAnswer(getattr(payload, "answer_id", None))
        if not verdict:
            return
        state = spine.resolveTargetTask()
        if state is None:
            return
        bus = ControlBus(state.task_id)
        gate = bus.getPendingGate()
        if not gate:
            return
        audit.record(getattr(payload, "user_id", None), verdict, state.task_id, "poll-vote")
        bus.decide(gate, verdict)
        LOG.info("poll vote resolved gate %s -> %s", gate, verdict)


async def setup(bot: dpy_commands.Bot) -> None:
    await bot.add_cog(EngagementCog(bot))
