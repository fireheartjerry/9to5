"""Admin cog: hot-reload extensions (/reload) + post a fresh live cockpit (/cockpit).

/reload is the keystone of the cog architecture -- it lets a feature cog be reloaded at
runtime without restarting the gateway. Owner-only.
"""
from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands as dpy_commands

import config
from notifications import commands as spine

LOG = config.getLogger("cog.admin")

_PREFIX = "notifications.bot.cogs."


class AdminCog(dpy_commands.Cog):
    def __init__(self, bot: dpy_commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="reload", description="Hot-reload a Nightclaw extension (owner only)")
    @app_commands.describe(extension="cog module name, e.g. ask_cog")
    async def reload(self, interaction: discord.Interaction, extension: str) -> None:
        if not spine.isAuthorized(interaction.user.id):
            return await interaction.response.send_message("Not authorized.", ephemeral=True)
        name = extension if extension.startswith(_PREFIX) else _PREFIX + extension
        try:
            await self.bot.reload_extension(name)
            await interaction.response.send_message(f" reloaded `{name}`", ephemeral=True)
        except Exception as e:  # noqa: BLE001
            LOG.warning("reload %s failed: %s", name, e)
            await interaction.response.send_message(f"reload failed: `{e}`", ephemeral=True)

    @app_commands.command(name="cockpit", description="Post a fresh Components-V2 cockpit for the run")
    async def cockpit(self, interaction: discord.Interaction) -> None:
        state = spine.resolveTargetTask()
        if state is None:
            return await interaction.response.send_message(spine.NO_TASK, ephemeral=True)
        from notifications import cv2
        from notifications import discord_bot
        comps, _flags = cv2.buildCockpit(state, state.meta.get("status", "executing"))
        await interaction.response.send_message("posting cockpit…", ephemeral=True)
        await asyncio.to_thread(discord_bot.createComponentsV2, comps)

    @app_commands.command(name="hud", description="Post the ANSI mission-console HUD (T8)")
    async def hud(self, interaction: discord.Interaction) -> None:
        state = spine.resolveTargetTask()
        if state is None:
            return await interaction.response.send_message(spine.NO_TASK, ephemeral=True)
        from notifications import console_hud
        from notifications import discord_bot
        body = console_hud.render(state, state.meta.get("status", "executing"))
        await interaction.response.send_message("posting HUD…", ephemeral=True)
        await asyncio.to_thread(discord_bot.postContent, body)


async def setup(bot: dpy_commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
