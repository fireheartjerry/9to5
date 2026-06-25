"""Run-control slash commands (owner + cooldown): pause / approve / reject / retry / add / skip / abort.
Thin shells over the commands spine (see notifications.slash helpers)."""
from __future__ import annotations

from discord import app_commands
from discord.ext import commands as dpy_commands

from control import ControlBus
from notifications import audit
from notifications import commands as spine
from notifications import slash


class ControlCog(dpy_commands.Cog):
    def __init__(self, bot: dpy_commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="pause", description="Pause the run")
    @slash.COOLDOWN
    async def pause(self, interaction) -> None:  # noqa: ANN001
        if await slash._guard(interaction):
            await slash._runControl(interaction, "pause")

    @app_commands.command(name="approve", description="Approve the pending gate")
    @slash.COOLDOWN
    async def approve(self, interaction) -> None:  # noqa: ANN001
        if await slash._guard(interaction):
            await slash._runControl(interaction, "approve")

    @app_commands.command(name="reject", description="Reject the pending gate")
    @slash.COOLDOWN
    async def reject(self, interaction) -> None:  # noqa: ANN001
        if await slash._guard(interaction):
            await slash._runControl(interaction, "reject")

    @app_commands.command(name="retry", description="Re-run the current subtask")
    @slash.COOLDOWN
    async def retry(self, interaction) -> None:  # noqa: ANN001
        if await slash._guard(interaction):
            await slash._runControl(interaction, "retry")

    @app_commands.command(name="add", description="Queue a new subtask")
    @app_commands.describe(title="Subtask title")
    @slash.COOLDOWN
    async def add(self, interaction, title: str) -> None:  # noqa: ANN001
        if await slash._guard(interaction):
            await slash._runControl(interaction, "add", title)

    @app_commands.command(name="skip", description="Skip a pending subtask")
    @app_commands.describe(subtask="Subtask id (e.g. st-003)")
    @app_commands.autocomplete(subtask=slash._subtaskAutocomplete)
    @slash.COOLDOWN
    async def skip(self, interaction, subtask: str) -> None:  # noqa: ANN001
        if await slash._guard(interaction):
            await slash._runControl(interaction, "skip", subtask)

    @app_commands.command(name="abort", description="Abort the run (asks for confirmation)")
    @slash.COOLDOWN
    async def abort(self, interaction) -> None:  # noqa: ANN001
        if not await slash._guard(interaction):
            return
        from notifications.views import confirmDestructive
        if await confirmDestructive(interaction, "abort the run"):
            state = spine.resolveTargetTask()
            if state is None:
                return await interaction.followup.send(spine.NO_TASK, ephemeral=True)
            audit.record(interaction.user.id, "abort", state.task_id, "slash")
            msg = spine.applyCommand(ControlBus(state.task_id), state, spine.Command("abort", ""))
            await interaction.followup.send(msg[:slash.MAX_REPLY], ephemeral=True)


async def setup(bot: dpy_commands.Bot) -> None:
    await bot.add_cog(ControlCog(bot))
