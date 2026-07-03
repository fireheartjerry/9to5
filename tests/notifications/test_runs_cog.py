"""Tests for run-lifecycle Discord cog helpers."""
from __future__ import annotations

from notifications.bot.cogs.runs_cog import RunsCog, setup


class _Bot:
    def __init__(self) -> None:
        self.cogs = []

    async def add_cog(self, cog) -> None:
        self.cogs.append(cog)


def test_setup_registers_runs_cog():
    bot = _Bot()

    import asyncio
    asyncio.run(setup(bot))

    assert len(bot.cogs) == 1
    assert isinstance(bot.cogs[0], RunsCog)
