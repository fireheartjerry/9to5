"""Tests for the Discord admin cog."""
from __future__ import annotations

from notifications.bot.cogs.admin import AdminCog, setup


class _Bot:
    def __init__(self) -> None:
        self.cogs = []

    async def add_cog(self, cog) -> None:
        self.cogs.append(cog)


def test_setup_registers_admin_cog():
    bot = _Bot()

    import asyncio
    asyncio.run(setup(bot))

    assert len(bot.cogs) == 1
    assert isinstance(bot.cogs[0], AdminCog)
