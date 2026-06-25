"""Tier 2 interactivity tests: pure timeline helpers + offline cog registration (slash
commands AND the two message context menus). No gateway connection."""
import asyncio
import unittest

import discord
from discord.ext import commands as dpy_commands

from notifications.bot.cogs import plan_cog


class _StubState:
    data = {"notifications": [
        {"at": "2026-06-25T11:00:00", "kind": "planning_start", "detail": "3 subtasks"},
        {"at": "2026-06-25T11:05:00", "kind": "subtask_done", "detail": "st-001"},
    ]}


class TimelineHelpers(unittest.TestCase):
    def test_lines(self):
        lines = plan_cog.timelineLines(_StubState())
        self.assertEqual(len(lines), 2)
        self.assertIn("planning_start", lines[0])
        self.assertIn("st-001", lines[1])

    def test_pages_empty(self):
        class Empty:
            data = {"notifications": []}
        pages = plan_cog._timelinePages(Empty())
        self.assertEqual(len(pages), 1)
        self.assertIn("no events", pages[0].description)

    def test_pages_paginate(self):
        class Many:
            data = {"notifications": [{"at": "x", "kind": "k", "detail": str(i)} for i in range(30)]}
        pages = plan_cog._timelinePages(Many(), per=12)
        self.assertEqual(len(pages), 3)   # 30 / 12 -> 3 pages


class CogRegistration(unittest.TestCase):
    def test_registers_slash_and_context_menus(self):
        async def run():
            intents = discord.Intents.default()
            bot = dpy_commands.Bot(command_prefix=dpy_commands.when_mentioned, intents=intents)
            try:
                await bot.load_extension("notifications.bot.cogs.plan_cog")
                slash = sorted(c.name for c in bot.tree.get_commands())
                ctx = sorted(c.name for c in bot.tree.get_commands(type=discord.AppCommandType.message))
                return slash, ctx
            finally:
                try:
                    await bot.close()
                except Exception:  # noqa: BLE001
                    pass
        slash, ctx = asyncio.run(run())
        self.assertIn("plan-edit", slash)
        self.assertIn("timeline", slash)
        self.assertIn("Send to Nightclaw as a goal", ctx)
        self.assertIn("Add as 9to5 subtask", ctx)


if __name__ == "__main__":
    unittest.main()
