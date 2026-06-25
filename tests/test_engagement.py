"""Tier 4 native-engagement tests: pure vote->verdict mapping, poll/event payload builders,
answer_id resolution, and offline cog load. No network, no gateway connection."""
import asyncio
import unittest

import discord
from discord.ext import commands as dpy_commands

from notifications import engagement
from notifications.bot.cogs import engagement_cog


class VoteMapping(unittest.TestCase):
    def test_yes_is_approve(self):
        self.assertEqual(engagement.voteToVerdict("✅ Yes"), "approve")

    def test_revise_is_reject_abort_is_abort(self):
        # 'Revise' declines the gate (reject); 'Abort' is the run kill-switch -- a DISTINCT verdict
        # routed to ControlBus.requestAbort(), never folded into reject (see engagement_cog._resolveGate).
        self.assertEqual(engagement.voteToVerdict("✏️ Revise"), "reject")
        self.assertEqual(engagement.voteToVerdict("🛑 Abort"), "abort")

    def test_unknown_is_none(self):
        self.assertIsNone(engagement.voteToVerdict("maybe later"))
        self.assertIsNone(engagement.voteToVerdict(""))


class PollPayload(unittest.TestCase):
    def test_gate_poll_shape(self):
        p = engagement.gatePollPayload("pre_pr")
        self.assertIn("pre_pr", p["question"]["text"])
        self.assertEqual(len(p["answers"]), 3)
        self.assertFalse(p["allow_multiselect"])
        self.assertGreaterEqual(p["duration"], 1)

    def test_duration_clamped(self):
        self.assertLessEqual(engagement.gatePollPayload("x", duration_hours=99999)["duration"], 768)

    def test_scheduled_event_shape(self):
        b = engagement.scheduledEventPayload("9to5 run", "2026-06-25T09:00:00Z", "2026-06-25T17:00:00Z")
        self.assertEqual(b["entity_type"], 3)        # EXTERNAL
        self.assertEqual(b["privacy_level"], 2)      # GUILD_ONLY
        self.assertEqual(b["scheduled_start_time"], "2026-06-25T09:00:00Z")


class AnswerResolution(unittest.TestCase):
    def test_answer_ids(self):
        self.assertEqual(engagement_cog.verdictForAnswer(1), "approve")   # ✅ Yes
        self.assertEqual(engagement_cog.verdictForAnswer(2), "reject")    # ✏️ Revise
        self.assertEqual(engagement_cog.verdictForAnswer(3), "abort")     # 🛑 Abort -> run kill-switch

    def test_out_of_range(self):
        for bad in (0, 4, None, "x"):
            self.assertIsNone(engagement_cog.verdictForAnswer(bad))


class CogLoad(unittest.TestCase):
    def test_loads_and_has_listener(self):
        async def run():
            intents = discord.Intents.default()
            bot = dpy_commands.Bot(command_prefix=dpy_commands.when_mentioned, intents=intents)
            try:
                await bot.load_extension("notifications.bot.cogs.engagement_cog")
                cog = bot.get_cog("EngagementCog")
                listeners = [n for n, _ in cog.get_listeners()]
                return listeners
            finally:
                try:
                    await bot.close()
                except Exception:  # noqa: BLE001
                    pass
        self.assertIn("on_raw_poll_vote_add", asyncio.run(run()))


if __name__ == "__main__":
    unittest.main()
