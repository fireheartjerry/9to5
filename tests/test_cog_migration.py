"""Lock the slash.py -> cogs migration: every legacy command is registered via a cog, no
duplicates, and the legacy registerSlashCommands entrypoint is gone. Offline (no gateway)."""
import asyncio
import unittest
from collections import Counter

import discord
from discord.ext import commands as dpy_commands

from notifications.bot import core

LEGACY = {"abort", "add", "approve", "audit", "diagnostics", "help", "log", "metrics", "pause",
          "ping", "plan", "reject", "resume", "retry", "run", "runs", "skip", "status", "wipe", "work"}
NEW = {"ask", "hud", "cockpit", "reload", "plan-edit", "timeline"}


def _load_all():
    async def run():
        intents = discord.Intents.default()
        intents.message_content = True
        bot = dpy_commands.Bot(command_prefix=dpy_commands.when_mentioned, intents=intents)
        try:
            for e in core.EXTENSIONS:
                await bot.load_extension(e)
            return sorted(c.name for c in bot.tree.get_commands()), sorted(bot.cogs)
        finally:
            try:
                await bot.close()
            except Exception:  # noqa: BLE001
                pass
    return asyncio.run(run())


class Migration(unittest.TestCase):
    def test_all_legacy_present(self):
        names, _ = _load_all()
        self.assertTrue(LEGACY <= set(names), f"missing: {sorted(LEGACY - set(names))}")

    def test_new_commands_present(self):
        names, _ = _load_all()
        self.assertTrue(NEW <= set(names), f"missing: {sorted(NEW - set(names))}")

    def test_no_duplicate_commands(self):
        names, _ = _load_all()
        self.assertEqual([n for n, c in Counter(names).items() if c > 1], [])

    def test_domain_cogs_loaded(self):
        _, cogs = _load_all()
        for c in ("ObserveCog", "ControlCog", "RunsCog"):
            self.assertIn(c, cogs)

    def test_legacy_entrypoint_gone(self):
        import notifications.slash as s
        self.assertFalse(hasattr(s, "registerSlashCommands"))
        self.assertTrue(hasattr(s, "_fmtUptime"))   # helper preserved (test_slash depends on it)


if __name__ == "__main__":
    unittest.main()
