"""Run-lifecycle slash commands: work / wipe / runs / run / resume.
Thin shells over work_launcher + branding (see notifications.slash helpers)."""
from __future__ import annotations

import asyncio

from discord import app_commands
from discord.ext import commands as dpy_commands

import config
from notifications import audit, branding, work_launcher
from notifications import commands as spine
from notifications import slash
from state.task import TaskState


class RunsCog(dpy_commands.Cog):
    def __init__(self, bot: dpy_commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="work", description="Start a 9TO5 run (blank = guided setup)")
    @app_commands.describe(goal="What to work on (blank opens guided setup)",
                           hours="Time horizon in hours", mode="watch or gated",
                           parallel="Concurrent subtasks", no_pr="Skip the PR",
                           work_dir="Working directory",
                           night_mode="Zero human interaction — no pings, no holds, auto-resume pauses")
    @app_commands.choices(mode=[app_commands.Choice(name="watch", value="watch"),
                                app_commands.Choice(name="gated", value="gated")])
    @slash.COOLDOWN
    async def work(self, interaction, goal: "str | None" = None, hours: "float | None" = None,
                   mode: "app_commands.Choice[str] | None" = None, parallel: "int | None" = None,
                   no_pr: "bool | None" = None, work_dir: "str | None" = None,
                   night_mode: "bool | None" = None) -> None:  # noqa: ANN001
        if not slash._ownerOk(interaction):
            return await interaction.response.send_message("Not authorized to launch runs.", ephemeral=True)
        if not goal:
            from notifications.views import WorkModal
            return await interaction.response.send_modal(WorkModal())
        await interaction.response.defer(ephemeral=True)

        if config.BROWSER_LAYER_ENABLED:
            from agents import browser_executor
            await interaction.followup.send(
                "Checking ChatGPT login — if a browser opens, **log in** (I'll detect it). "
                "Waiting up to 5 minutes…", ephemeral=True)
            logged_in = await asyncio.to_thread(browser_executor.preflightLogin, 300, 3)
            if not logged_in:
                await interaction.followup.send(
                    "ChatGPT login timed out (5 min). Run aborted — re-run `/work` after logging in.",
                    ephemeral=True)
                return
            await interaction.followup.send("ChatGPT logged in. Starting run…", ephemeral=True)

        req = work_launcher.WorkRequest(
            goal=goal, hours=work_launcher.parseHours(hours),
            mode=(mode.value if mode else "watch"), parallel=parallel or 1,
            no_pr=bool(no_pr), work_dir=work_dir or None, night_mode=bool(night_mode))
        audit.record(interaction.user.id, "work", None, "slash")
        reply = await asyncio.to_thread(work_launcher.launchOrError, req)
        await interaction.followup.send(reply[:slash.MAX_REPLY], ephemeral=True)

    @app_commands.command(name="wipe", description="Factory reset — granular wipe of state, vault, and logs")
    @slash.COOLDOWN
    async def wipe(self, interaction) -> None:  # noqa: ANN001
        if not slash._ownerOk(interaction):
            return await interaction.response.send_message("Not authorized.", ephemeral=True)
        from notifications.views import WipeSetupView
        audit.record(interaction.user.id, "wipe", None, "slash")
        await interaction.response.send_message(
            "**Memory Wipe** — select categories and backup preference, then proceed:",
            view=WipeSetupView(interaction.user.id), ephemeral=True)

    @app_commands.command(name="runs", description="List recent runs")
    async def runs(self, interaction) -> None:  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        summaries = TaskState.listRecent(40)
        _, total = branding.runsEmbed(summaries, 0)
        pages = [slash._embed(branding.runsEmbed(summaries, p)[0]) for p in range(total)]
        from notifications.views import Paginator
        if total > 1:
            await interaction.followup.send(embed=pages[0],
                                            view=Paginator(interaction.user.id, pages), ephemeral=True)
        else:
            await interaction.followup.send(embed=pages[0], ephemeral=True)

    @app_commands.command(name="run", description="Inspect a run by id")
    @app_commands.describe(task_id="Task id")
    @app_commands.autocomplete(task_id=slash._taskAutocomplete)
    async def run(self, interaction, task_id: str) -> None:  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        if not work_launcher.taskExists(task_id):
            return await interaction.followup.send(f" No such task `{task_id}`.", ephemeral=True)
        state = TaskState.loadSafe(task_id)
        if state is None:
            return await interaction.followup.send(
                f" Task `{task_id}` exists but its state file is unreadable (corrupt JSON).", ephemeral=True)
        await interaction.followup.send(embed=slash._embed(branding.runEmbed(state)), ephemeral=True)

    @app_commands.command(name="resume", description="Resume a paused run, or resume a prior run by id")
    @app_commands.describe(task_id="(optional) prior task id to resume; omit to unpause the current run")
    @app_commands.autocomplete(task_id=slash._taskAutocomplete)
    @slash.COOLDOWN
    async def resume(self, interaction, task_id: "str | None" = None) -> None:  # noqa: ANN001
        if not slash._ownerOk(interaction):
            return await interaction.response.send_message("Not authorized.", ephemeral=True)
        if not task_id:
            return await slash._runControl(interaction, "resume")
        await interaction.response.defer(ephemeral=True)
        audit.record(interaction.user.id, "resume", task_id, "slash")
        reply = await asyncio.to_thread(work_launcher.resumeOrError, task_id)
        await interaction.followup.send(reply[:slash.MAX_REPLY], ephemeral=True)


async def setup(bot: dpy_commands.Bot) -> None:
    await bot.add_cog(RunsCog(bot))
