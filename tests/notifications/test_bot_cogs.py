"""Offline gateway-cog tests: the feature cogs load WITHOUT a connection and register their
slash commands on the tree, and the NightclawBot constructs. No token, no network."""
import asyncio
import unittest

import discord
from discord.ext import commands as dpy_commands

from notifications.bot import core


def _load(exts):
    async def run():
        intents = discord.Intents.default()
        intents.message_content = True
        bot = dpy_commands.Bot(command_prefix=dpy_commands.when_mentioned, intents=intents)
        try:
            for e in exts:
                await bot.load_extension(e)
            return sorted(c.name for c in bot.tree.get_commands())
        finally:
            try:
                await bot.close()
            except Exception:  # noqa: BLE001
                pass
    return asyncio.run(run())


class CogLoader(unittest.TestCase):
    def test_extensions_nonempty(self):
        self.assertTrue(core.EXTENSIONS)

    def test_all_extensions_load_and_register(self):
        names = _load(core.EXTENSIONS)
        for cmd in ("ask", "reload", "cockpit"):
            self.assertIn(cmd, names)

    def test_buildBot_constructs(self):
        bot = core.buildBot()
        self.assertEqual(type(bot).__name__, "NightclawBot")
        self.assertTrue(bot.intents.message_content)
