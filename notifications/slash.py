"""All 9TO5 slash commands, registered onto a CommandTree. Thin shells over the
commands.py spine / work_launcher / branding builders. Read commands are open;
mutating commands require owner + cooldown. Autocomplete for subtask/task ids."""
from __future__ import annotations

import asyncio
import time

import discord
from discord import app_commands

import config
import health
from control import ControlBus
from notifications import audit, branding, commands, metrics, work_launcher
from state.task import TaskState

LOG = config.getLogger("slash")
MAX_REPLY = config.DISCORD_MAX_CONTENT - 100


def _fmtUptime(started_at: float) -> str:
    secs = max(0, int(time.time() - started_at))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def _embed(d: dict) -> discord.Embed:
    return discord.Embed.from_dict(d)


def registerSlashCommands(tree: "app_commands.CommandTree", client: "discord.Client",
                          started_at: float) -> None:
    cooldown = app_commands.checks.cooldown(config.COOLDOWN_RATE, config.COOLDOWN_PER,
                                            key=lambda i: i.user.id)

    def _ownerOk(interaction) -> bool:
        return commands.isAuthorized(interaction.user.id)

    async def _runControl(interaction, name: str, arg: str = "") -> None:
        await interaction.response.defer(ephemeral=True)
        state = commands.resolveTargetTask()
        if state is None:
            return await interaction.followup.send(commands.NO_TASK, ephemeral=True)
        if commands.COMMAND_REGISTRY.get(name, {}).get("mutating"):   # audit control actions only (not /log)
            audit.record(interaction.user.id, name, state.task_id, "slash")
        msg = commands.applyCommand(ControlBus(state.task_id), state, commands.Command(name, arg))
        await interaction.followup.send(msg[:MAX_REPLY], ephemeral=True)

    # ---------- read commands (open to all) ----------
    @tree.command(name="status", description="Current run status")
    async def status(interaction):  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        state = commands.resolveTargetTask()
        if state is None:
            return await interaction.followup.send(commands.NO_TASK, ephemeral=True)
        e = branding.statusEmbed(state, ControlBus(state.task_id), uptime=_fmtUptime(started_at))
        await interaction.followup.send(embed=_embed(e), ephemeral=True)

    @tree.command(name="plan", description="The subtask plan")
    async def plan(interaction):  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        state = commands.resolveTargetTask()
        if state is None:
            return await interaction.followup.send(commands.NO_TASK, ephemeral=True)
        _, total = branding.planEmbed(state, 0)
        pages = [_embed(branding.planEmbed(state, p)[0]) for p in range(total)]
        from notifications.views import Paginator
        if total > 1:
            await interaction.followup.send(embed=pages[0], view=Paginator(interaction.user.id, pages),
                                            ephemeral=True)
        else:
            await interaction.followup.send(embed=pages[0], ephemeral=True)

    @tree.command(name="log", description="Obsidian index + web dashboard URL")
    async def log(interaction):  # noqa: ANN001
        await _runControl(interaction, "log")

    @tree.command(name="help", description="Show the command list")
    async def help_(interaction):  # noqa: ANN001
        await interaction.response.send_message(embed=_embed(branding.helpEmbed()), ephemeral=True)

    @tree.command(name="ping", description="Bot latency, uptime, version")
    async def ping(interaction):  # noqa: ANN001
        ms = round(client.latency * 1000) if client.latency else 0
        e = branding.pingEmbed(ms, _fmtUptime(started_at), config.VERSION)
        await interaction.response.send_message(embed=_embed(e), ephemeral=True)

    @tree.command(name="diagnostics", description="Environment health checks")
    async def diagnostics(interaction):  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        checks = await asyncio.to_thread(health.collectHealth)
        await interaction.followup.send(embed=_embed(branding.diagnosticsEmbed(checks)), ephemeral=True)

    @tree.command(name="metrics", description="Aggregate run metrics")
    async def metrics_(interaction):  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        m = await asyncio.to_thread(metrics.compute)
        await interaction.followup.send(embed=_embed(branding.metricsEmbed(m)), ephemeral=True)

    @tree.command(name="audit", description="Recent control actions")
    async def audit_(interaction):  # noqa: ANN001
        await interaction.response.send_message(
            embed=_embed(branding.auditEmbed(audit.recent(20))), ephemeral=True)

    # ---------- mutating commands (owner + cooldown) ----------
    async def _guard(interaction) -> bool:
        if not _ownerOk(interaction):
            await interaction.response.send_message("⛔ Not authorized to control runs.", ephemeral=True)
            return False
        return True

    @tree.command(name="pause", description="Pause the run")
    @cooldown
    async def pause(interaction):  # noqa: ANN001
        if await _guard(interaction):
            await _runControl(interaction, "pause")

    @tree.command(name="approve", description="Approve the pending gate")
    @cooldown
    async def approve(interaction):  # noqa: ANN001
        if await _guard(interaction):
            await _runControl(interaction, "approve")

    @tree.command(name="reject", description="Reject the pending gate")
    @cooldown
    async def reject(interaction):  # noqa: ANN001
        if await _guard(interaction):
            await _runControl(interaction, "reject")

    @tree.command(name="retry", description="Re-run the current subtask")
    @cooldown
    async def retry(interaction):  # noqa: ANN001
        if await _guard(interaction):
            await _runControl(interaction, "retry")

    @tree.command(name="add", description="Queue a new subtask")
    @app_commands.describe(title="Subtask title")
    @cooldown
    async def add(interaction, title: str):  # noqa: ANN001
        if await _guard(interaction):
            await _runControl(interaction, "add", title)

    async def _subtaskAutocomplete(interaction, current: str):  # noqa: ANN001
        state = commands.resolveTargetTask()
        if state is None:
            return []
        out = []
        for s in state.subtasks:
            # Only pending subtasks can actually be skipped between steps (an in_progress one
            # has already started and cannot be yanked mid-flight); don't offer the rest.
            if s["status"] == "pending" and current.lower() in s["subtask_id"].lower():
                out.append(app_commands.Choice(name=f"{s['subtask_id']} — {s['title'][:60]}",
                                               value=s["subtask_id"]))
        return out[:25]

    @tree.command(name="skip", description="Skip a pending subtask")
    @app_commands.describe(subtask="Subtask id (e.g. st-003)")
    @app_commands.autocomplete(subtask=_subtaskAutocomplete)
    @cooldown
    async def skip(interaction, subtask: str):  # noqa: ANN001
        if await _guard(interaction):
            await _runControl(interaction, "skip", subtask)

    @tree.command(name="abort", description="Abort the run (asks for confirmation)")
    @cooldown
    async def abort(interaction):  # noqa: ANN001
        if not await _guard(interaction):
            return
        from notifications.views import confirmDestructive
        if await confirmDestructive(interaction, "abort the run"):
            state = commands.resolveTargetTask()
            if state is None:
                return await interaction.followup.send(commands.NO_TASK, ephemeral=True)
            audit.record(interaction.user.id, "abort", state.task_id, "slash")
            msg = commands.applyCommand(ControlBus(state.task_id), state, commands.Command("abort", ""))
            await interaction.followup.send(msg[:MAX_REPLY], ephemeral=True)

    # ---------- run lifecycle ----------
    async def _taskAutocomplete(interaction, current: str):  # noqa: ANN001
        out = []
        for s in TaskState.listRecent(25):
            if current.lower() in s["task_id"].lower():
                out.append(app_commands.Choice(
                    name=f"{s['task_id'][:8]} — [{s['status']}] {s['goal'][:50]}",
                    value=s["task_id"]))
        return out[:25]

    @tree.command(name="work", description="Start a 9TO5 run (blank = guided setup)")
    @app_commands.describe(goal="What to work on (blank opens guided setup)",
                           hours="Time horizon in hours", mode="watch or gated",
                           parallel="Concurrent subtasks", no_pr="Skip the PR",
                           work_dir="Working directory",
                           night_mode="Zero human interaction — no pings, no holds, auto-resume pauses")
    @app_commands.choices(mode=[app_commands.Choice(name="watch", value="watch"),
                                app_commands.Choice(name="gated", value="gated")])
    @cooldown
    async def work(interaction, goal: "str | None" = None, hours: "float | None" = None,
                   mode: "app_commands.Choice[str] | None" = None, parallel: "int | None" = None,
                   no_pr: "bool | None" = None, work_dir: "str | None" = None,
                   night_mode: "bool | None" = None):  # noqa: ANN001
        if not _ownerOk(interaction):
            return await interaction.response.send_message("⛔ Not authorized to launch runs.", ephemeral=True)
        if not goal:
            from notifications.views import WorkModal
            return await interaction.response.send_modal(WorkModal())
        await interaction.response.defer(ephemeral=True)

        # Pre-flight: ensure ChatGPT is logged in before spawning the run. The whole open->poll->close
        # runs on browser_executor's ONE dedicated thread (sync Playwright is thread-affine and must
        # never be driven from the bot's asyncio loop), and the close releases the profile lock so the
        # spawned orchestrator can open it.
        if config.BROWSER_LAYER_ENABLED:
            from agents import browser_executor
            await interaction.followup.send(
                "🔐 Checking ChatGPT login — if a browser opens, **log in** (I'll detect it). "
                "Waiting up to 5 minutes…", ephemeral=True)
            logged_in = await asyncio.to_thread(browser_executor.preflightLogin, 300, 3)
            if not logged_in:
                await interaction.followup.send(
                    "❌ ChatGPT login timed out (5 min). Run aborted — re-run `/work` after logging in.",
                    ephemeral=True)
                return
            await interaction.followup.send("✅ ChatGPT logged in. Starting run…", ephemeral=True)

        req = work_launcher.WorkRequest(
            goal=goal, hours=work_launcher.parseHours(hours),
            mode=(mode.value if mode else "watch"), parallel=parallel or 1,
            no_pr=bool(no_pr), work_dir=work_dir or None,
            night_mode=bool(night_mode))
        audit.record(interaction.user.id, "work", None, "slash")
        reply = await asyncio.to_thread(work_launcher.launchOrError, req)
        await interaction.followup.send(reply[:MAX_REPLY], ephemeral=True)

    @tree.command(name="wipe", description="Factory reset — granular wipe of state, vault, and logs")
    @cooldown
    async def wipe(interaction):  # noqa: ANN001
        if not _ownerOk(interaction):
            return await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
        from notifications.views import WipeSetupView
        audit.record(interaction.user.id, "wipe", None, "slash")
        await interaction.response.send_message(
            "**Memory Wipe** — select categories and backup preference, then proceed:",
            view=WipeSetupView(interaction.user.id),
            ephemeral=True,
        )

    @tree.command(name="runs", description="List recent runs")
    async def runs(interaction):  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        summaries = TaskState.listRecent(40)
        _, total = branding.runsEmbed(summaries, 0)
        pages = [_embed(branding.runsEmbed(summaries, p)[0]) for p in range(total)]
        from notifications.views import Paginator
        if total > 1:
            await interaction.followup.send(embed=pages[0], view=Paginator(interaction.user.id, pages),
                                            ephemeral=True)
        else:
            await interaction.followup.send(embed=pages[0], ephemeral=True)

    @tree.command(name="run", description="Inspect a run by id")
    @app_commands.describe(task_id="Task id")
    @app_commands.autocomplete(task_id=_taskAutocomplete)
    async def run(interaction, task_id: str):  # noqa: ANN001
        await interaction.response.defer(ephemeral=True)
        if not work_launcher.taskExists(task_id):
            return await interaction.followup.send(f"❌ No such task `{task_id}`.", ephemeral=True)
        state = TaskState.loadSafe(task_id)
        if state is None:
            return await interaction.followup.send(f"❌ Task `{task_id}` exists but its state file is "
                                                   "unreadable (corrupt JSON).", ephemeral=True)
        await interaction.followup.send(embed=_embed(branding.runEmbed(state)), ephemeral=True)

    @tree.command(name="resume", description="Resume a paused run, or resume a prior run by id")
    @app_commands.describe(task_id="(optional) prior task id to resume; omit to unpause the current run")
    @app_commands.autocomplete(task_id=_taskAutocomplete)
    @cooldown
    async def resume(interaction, task_id: "str | None" = None):  # noqa: ANN001
        # UNIFIED /resume: no id -> unpause the current run (spine 'resume'); id -> resume that run.
        # (A single command name avoids a duplicate-registration collision with the control resume.)
        if not _ownerOk(interaction):
            return await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
        if not task_id:
            return await _runControl(interaction, "resume")
        await interaction.response.defer(ephemeral=True)
        audit.record(interaction.user.id, "resume", task_id, "slash")
        reply = await asyncio.to_thread(work_launcher.resumeOrError, task_id)
        await interaction.followup.send(reply[:MAX_REPLY], ephemeral=True)
