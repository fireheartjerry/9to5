"""Tests for read-only Discord observability cog wiring."""
from __future__ import annotations

from notifications.bot.cogs.observe_cog import ObserveCog, setup


class _Bot:
    started_at = 0.0
    latency = 0.123

    def __init__(self) -> None:
        self.cogs = []

    async def add_cog(self, cog) -> None:
        self.cogs.append(cog)


def test_setup_registers_observe_cog():
    bot = _Bot()

    import asyncio
    asyncio.run(setup(bot))

    assert len(bot.cogs) == 1
    assert isinstance(bot.cogs[0], ObserveCog)
    assert isinstance(bot.cogs[0]._uptime(), str)
