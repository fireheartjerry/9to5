"""Shared helpers for the slash-command cogs.

The commands themselves now live in ``notifications.bot.cogs.{observe,control,runs}_cog``
(proper discord.ext.commands Cogs). This module holds the thin plumbing they all share:
the cooldown, the owner guard, the control-dispatch shell, and the subtask/task autocompletes.
Pure-ish -- importable + unit-testable without a gateway.
"""
from __future__ import annotations

import time

import discord
from discord import app_commands

import config
from control import ControlBus
from notifications import audit
from notifications import commands
from state.task import TaskState

LOG = config.getLogger("slash")
MAX_REPLY = config.DISCORD_MAX_CONTENT - 100

# One cooldown for the mutating commands (per-user), shared exactly as the legacy suite did.
COOLDOWN = app_commands.checks.cooldown(config.COOLDOWN_RATE, config.COOLDOWN_PER,
                                        key=lambda i: i.user.id)


def _fmtUptime(started_at: float) -> str:
    secs = max(0, int(time.time() - started_at))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def _embed(d: dict) -> "discord.Embed":
    return discord.Embed.from_dict(d)


def _ownerOk(interaction) -> bool:  # noqa: ANN001
    return commands.isAuthorized(interaction.user.id)


async def _runControl(interaction, name: str, arg: str = "") -> None:  # noqa: ANN001
    """defer -> resolve task -> audit (mutating only) -> apply via the spine -> reply ephemerally."""
    await interaction.response.defer(ephemeral=True)
    state = commands.resolveTargetTask()
    if state is None:
        return await interaction.followup.send(commands.NO_TASK, ephemeral=True)
    if commands.COMMAND_REGISTRY.get(name, {}).get("mutating"):
        audit.record(interaction.user.id, name, state.task_id, "slash")
    msg = commands.applyCommand(ControlBus(state.task_id), state, commands.Command(name, arg))
    await interaction.followup.send(msg[:MAX_REPLY], ephemeral=True)


async def _guard(interaction) -> bool:  # noqa: ANN001
    if not _ownerOk(interaction):
        await interaction.response.send_message("Not authorized to control runs.", ephemeral=True)
        return False
    return True


async def _subtaskAutocomplete(interaction, current: str):  # noqa: ANN001
    state = commands.resolveTargetTask()
    if state is None:
        return []
    out = []
    for s in state.subtasks:
        # only PENDING subtasks can be skipped between steps; don't offer the rest
        if s["status"] == "pending" and current.lower() in s["subtask_id"].lower():
            out.append(app_commands.Choice(name=f"{s['subtask_id']} — {s['title'][:60]}",
                                           value=s["subtask_id"]))
    return out[:25]


async def _taskAutocomplete(interaction, current: str):  # noqa: ANN001
    out = []
    for s in TaskState.listRecent(25):
        if current.lower() in s["task_id"].lower():
            out.append(app_commands.Choice(
                name=f"{s['task_id'][:8]} — [{s['status']}] {s['goal'][:50]}", value=s["task_id"]))
    return out[:25]
