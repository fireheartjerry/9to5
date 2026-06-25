"""Observability slash commands (read-only, open to all):
status / plan / log / help / ping / diagnostics / metrics / audit.
Thin shells over the commands spine + branding builders (see notifications.slash helpers)."""
from __future__ import annotations

import asyncio

from discord import app_commands
from discord.ext import commands as dpy_commands

import config
import health
from control import ControlBus
from notifications import audit, branding, metrics
from notifications import commands as spine
from notifications import slash


class ObserveCog(dpy_commands.Cog):
    def __init__(self, bot: dpy_commands.Bot) -> None:
        self.bot = bot

    def _uptime(self) -> str:
        return slash._fmtUptime(getattr(self.bot, "started_at", 0.0))

    @app_commands.command(name="status", description="Current run status")
    async def status(self, interaction) -> None:  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        state = spine.resolveTargetTask()
        if state is None:
            return await interaction.followup.send(spine.NO_TASK, ephemeral=True)
        e = branding.statusEmbed(state, ControlBus(state.task_id), uptime=self._uptime())
        await interaction.followup.send(embed=slash._embed(e), ephemeral=True)

    @app_commands.command(name="plan", description="The subtask plan")
    async def plan(self, interaction) -> None:  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        state = spine.resolveTargetTask()
        if state is None:
            return await interaction.followup.send(spine.NO_TASK, ephemeral=True)
        _, total = branding.planEmbed(state, 0)
        pages = [slash._embed(branding.planEmbed(state, p)[0]) for p in range(total)]
        from notifications.views import Paginator
        if total > 1:
            await interaction.followup.send(embed=pages[0],
                                            view=Paginator(interaction.user.id, pages), ephemeral=True)
        else:
            await interaction.followup.send(embed=pages[0], ephemeral=True)

    @app_commands.command(name="log", description="Obsidian index + web dashboard URL")
    async def log(self, interaction) -> None:  # noqa: ANN001
        await slash._runControl(interaction, "log")

    @app_commands.command(name="help", description="Show the command list")
    async def help_(self, interaction) -> None:  # noqa: ANN001
        await interaction.response.send_message(embed=slash._embed(branding.helpEmbed()), ephemeral=True)

    @app_commands.command(name="ping", description="Bot latency, uptime, version")
    async def ping(self, interaction) -> None:  # noqa: ANN001
        ms = round(self.bot.latency * 1000) if self.bot.latency else 0
        e = branding.pingEmbed(ms, self._uptime(), config.VERSION)
        await interaction.response.send_message(embed=slash._embed(e), ephemeral=True)

    @app_commands.command(name="diagnostics", description="Environment health checks")
    async def diagnostics(self, interaction) -> None:  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        checks = await asyncio.to_thread(health.collectHealth)
        await interaction.followup.send(embed=slash._embed(branding.diagnosticsEmbed(checks)), ephemeral=True)

    @app_commands.command(name="metrics", description="Aggregate run metrics")
    async def metrics_(self, interaction) -> None:  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        m = await asyncio.to_thread(metrics.compute)
        await interaction.followup.send(embed=slash._embed(branding.metricsEmbed(m)), ephemeral=True)

    @app_commands.command(name="audit", description="Recent control actions")
    async def audit_(self, interaction) -> None:  # noqa: ANN001
        await interaction.response.send_message(
            embed=slash._embed(branding.auditEmbed(audit.recent(20))), ephemeral=True)


async def setup(bot: dpy_commands.Bot) -> None:
    await bot.add_cog(ObserveCog(bot))
