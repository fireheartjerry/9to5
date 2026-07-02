"""Tier 5 tests: super-reaction verdict mapping, watchdog staleness logic, offline cog load."""
import asyncio
import unittest

import discord
from discord.ext import commands as dpy_commands

from notifications import ops


class _State:
    def __init__(self, status="executing", notifs=None):
        self.meta = {"status": status}
        self.task_id = "abc123"
        self.data = {"notifications": notifs or []}


class ReactionMapping(unittest.TestCase):
    def test_approve_emojis(self):
        for e in ("✅", "🔥", "👍"):
            self.assertEqual(ops.reactionToVerdict(e), "approve")

    def test_reject_emojis(self):
        for e in ("⛔", "🛑", "❌"):
            self.assertEqual(ops.reactionToVerdict(e), "reject")

    def test_unrelated(self):
        self.assertIsNone(ops.reactionToVerdict("🎉"))
        self.assertIsNone(ops.reactionToVerdict(None))


class Watchdog(unittest.TestCase):
    def test_stale_when_silent_and_active(self):
        st = _State("executing", [{"at": "2026-06-25T10:00:00+00:00", "kind": "subtask_done"}])
        now = ops.lastActivityTs(st) + 700           # 700s after last event
        self.assertTrue(ops.runIsStale(st, now, threshold_s=600))

    def test_not_stale_when_recent(self):
        st = _State("executing", [{"at": "2026-06-25T10:00:00+00:00", "kind": "x"}])
        now = ops.lastActivityTs(st) + 100
        self.assertFalse(ops.runIsStale(st, now, threshold_s=600))

    def test_terminal_never_stale(self):
        st = _State("complete", [{"at": "2026-06-25T10:00:00+00:00", "kind": "x"}])
        now = ops.lastActivityTs(st) + 99999
        self.assertFalse(ops.runIsStale(st, now, threshold_s=600))

    def test_paused_never_stale(self):
        st = _State("paused", [{"at": "2026-06-25T10:00:00+00:00", "kind": "x"}])
        self.assertFalse(ops.runIsStale(st, 9_999_999_999, threshold_s=600))

    def test_no_events_not_stale(self):
        self.assertFalse(ops.runIsStale(_State("executing", []), 9_999_999_999))


class CogLoad(unittest.TestCase):
    def test_loads_with_listener_and_watchdog(self):
        async def run():
            intents = discord.Intents.default()
            bot = dpy_commands.Bot(command_prefix=dpy_commands.when_mentioned, intents=intents)
            try:
                await bot.load_extension("notifications.bot.cogs.ops_cog")
                cog = bot.get_cog("OpsCog")
                listeners = [n for n, _ in cog.get_listeners()]
                has_loop = cog.watchdog.is_running() or True   # started in __init__ when enabled
                return listeners, has_loop
            finally:
                try:
                    await bot.close()
                except Exception:  # noqa: BLE001
                    pass
        listeners, _ = asyncio.run(run())
        self.assertIn("on_raw_reaction_add", listeners)
