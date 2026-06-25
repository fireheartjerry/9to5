"""Tier 5 realtime ops + safety: super-reaction quick-approve + a watchdog that alerts when
the orchestrator goes silent. Thin gateway shell over the pure ``notifications.ops`` logic.
"""
from __future__ import annotations

import asyncio
import time

from discord.ext import commands as dpy_commands
from discord.ext import tasks

import config
from control import ControlBus
from notifications import audit
from notifications import commands as spine
from notifications import discord_bot as discord
from notifications import ops

LOG = config.getLogger("cog.ops")


class OpsCog(dpy_commands.Cog):
    def __init__(self, bot: dpy_commands.Bot) -> None:
        self.bot = bot
        self._alerted: set = set()
        if config.WATCHDOG_ENABLED:
            self.watchdog.start()

    def cog_unload(self) -> None:
        self.watchdog.cancel()

    @dpy_commands.Cog.listener()
    async def on_raw_reaction_add(self, payload) -> None:  # noqa: ANN001
        """Owner reacts / (or /) on the gate notice -> resolve the pending gate.
        Works for normal AND super (burst) reactions -- same emoji."""
        if not config.REACTION_APPROVE:
            return
        owner = (config.DISCORD_HUMAN_USER_ID or "").strip()
        if owner.isdigit() and getattr(payload, "user_id", None) != int(owner):
            return
        emoji = getattr(getattr(payload, "emoji", None), "name", None) or getattr(payload, "emoji", None)
        verdict = ops.reactionToVerdict(emoji)
        if not verdict:
            return
        state = spine.resolveTargetTask()
        if state is None:
            return
        bus = ControlBus(state.task_id)
        gate = bus.getPendingGate()
        if not gate:
            return
        audit.record(getattr(payload, "user_id", None), verdict, state.task_id, "reaction")
        bus.decide(gate, verdict)
        LOG.info("super-reaction resolved gate %s -> %s", gate, verdict)

    @tasks.loop(seconds=60)
    async def watchdog(self) -> None:
        try:
            state = spine.resolveTargetTask()
            if state is None:
                return
            if ops.runIsStale(state, time.time()):
                if state.task_id not in self._alerted:
                    self._alerted.add(state.task_id)
                    await asyncio.to_thread(
                        discord.sendEmbed,
                        discord.noticeEmbed(
                            f"Run `{state.task_id[:8]}` has emitted no event for "
                            f">{ops.STALE_SECONDS // 60}m — possible stall.", "Watchdog"))
            else:
                self._alerted.discard(state.task_id)
        except Exception:  # noqa: BLE001 -- the watchdog must never crash the gateway
            LOG.warning("watchdog tick failed", exc_info=True)

    @watchdog.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: dpy_commands.Bot) -> None:
    await bot.add_cog(OpsCog(bot))
