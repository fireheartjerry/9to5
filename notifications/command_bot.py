"""Gateway command bot -- rich, interactive Discord control + /work launcher.

Runs as its own long-lived process:  venv\\Scripts\\python -m notifications.command_bot

All '!' grammar, authorization, and task resolution live in notifications.commands (the
single source of truth, shared with the orchestrator poller). This module is the thin
discord.py shell: it authorizes, defers, delegates, and renders. It also registers the
/work slash command (optional params; modal+dropdown onboarding when blank) which spawns
a full run via notifications.work_launcher.
"""
from __future__ import annotations

import time

import config
from control import ControlBus
from notifications import commands, work_launcher
from notifications import discord_bot as discord
from state.task import TaskState

LOG = config.getLogger("command_bot")

MAX_REPLY_CHARS = config.DISCORD_MAX_CONTENT - 100


# ---- pure-ish handlers (delegate to commands.py) ---------------------------
def handleCommand(content: str) -> str:
    """Parse + apply a '!' command against the latest task. '' if not a command."""
    cmd = commands.parseCommand(content)
    if cmd is None:
        return ""
    state = commands.resolveTargetTask()
    if state is None:
        return commands.NO_TASK
    return commands.applyCommand(ControlBus(state.task_id), state, cmd)


def handleButton(custom_id: str) -> str:
    state = commands.resolveTargetTask()
    if state is None:
        return commands.NO_TASK
    bus = ControlBus(state.task_id)
    if custom_id == "sc_abort":
        bus.requestAbort()
        return "🛑 Abort requested — run stops after the current step."
    if custom_id == "sc_skip":
        cur = next((s for s in state.subtasks if s["status"] == "in_progress"), None)
        if cur:
            bus.pushOp({"op": "skip", "subtask_id": cur["subtask_id"]})
            return f"⏭️ Skipping `{cur['subtask_id']}`."
        return "Nothing in progress to skip."
    if custom_id == "sc_answer":
        return "✍️ Type your answer as a normal message; the orchestrator will pick it up."
    return "Unknown action."


def _launchOrError(req: "work_launcher.WorkRequest") -> str:
    """Central launch path shared by every entry: validate -> block-if-active -> spawn."""
    errs = work_launcher.validate(req)
    if errs:
        return "❌ " + "  ".join(errs)
    active = work_launcher.activeRun()
    if active is not None:
        return (f"⛔ A run is already active (`{active.task_id[:8]}` · "
                f"`{active.meta.get('status')}`). Abort it first with `!abort`.")
    t0 = time.time()
    try:
        pid = work_launcher.spawn(req)
    except Exception as e:  # noqa: BLE001
        LOG.exception("spawn failed")
        return f"❌ Launch failed: {e}"
    task_id = None
    for _ in range(20):
        task_id = work_launcher.newestTaskSince(t0)
        if task_id:
            break
        time.sleep(0.5)
    web = f"http://127.0.0.1:{config.WEB_DASHBOARD_PORT}/"
    if task_id:
        return (f"✅ Launched run `{task_id[:8]}` (pid {pid}) · mode `{req.mode}` · "
                f"{req.hours}h · parallel {req.parallel}\n{web}")
    return (f"✅ Launch started (pid {pid}) · mode `{req.mode}` · {req.hours}h. "
            f"If no dashboard appears shortly, check `logs\\work-*.log`.\n{web}")


def runCommandBot() -> None:  # pragma: no cover -- long-lived gateway process
    import discord as dpy
    from discord import app_commands

    if not config.DISCORD_BOT_TOKEN:
        LOG.error("DISCORD_BOT_TOKEN missing; cannot start command bot")
        return

    intents = dpy.Intents.default()
    intents.message_content = True
    client = dpy.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    _synced = {"done": False}

    # ---------- /work onboarding (modal -> dropdown view) ----------
    class WorkSetupView(dpy.ui.View):
        def __init__(self, owner_id: int, goal: str, hours: float, work_dir: str | None):
            super().__init__(timeout=300)
            self.owner_id = owner_id
            self.req = work_launcher.WorkRequest(goal=goal, hours=hours, work_dir=work_dir or None)

        async def interaction_check(self, interaction: "dpy.Interaction") -> bool:
            if not commands.isAuthorized(interaction.user.id):
                await interaction.response.send_message("Not authorized.", ephemeral=True)
                return False
            return True

        @dpy.ui.select(placeholder="Control mode", options=[
            dpy.SelectOption(label="watch (autonomous + abort)", value="watch", default=True),
            dpy.SelectOption(label="gated (approve plan + PR)", value="gated"),
        ])
        async def _mode(self, interaction, select):  # noqa: ANN001
            self.req.mode = select.values[0]
            await interaction.response.defer()

        @dpy.ui.select(placeholder="Parallelism", options=[
            dpy.SelectOption(label=f"{i} concurrent subtask(s)", value=str(i), default=(i == 1))
            for i in range(1, work_launcher.MAX_PARALLEL + 1)
        ])
        async def _parallel(self, interaction, select):  # noqa: ANN001
            self.req.parallel = int(select.values[0])
            await interaction.response.defer()

        @dpy.ui.select(placeholder="Pull request", options=[
            dpy.SelectOption(label="Create a PR when done", value="pr", default=True),
            dpy.SelectOption(label="Skip PR", value="nopr"),
        ])
        async def _pr(self, interaction, select):  # noqa: ANN001
            self.req.no_pr = (select.values[0] == "nopr")
            await interaction.response.defer()

        @dpy.ui.button(label="Launch", style=dpy.ButtonStyle.success)
        async def _launch(self, interaction, button):  # noqa: ANN001
            for c in self.children:
                c.disabled = True
            await interaction.response.edit_message(content="🚀 Launching…", view=self)
            reply = _launchOrError(self.req)
            await interaction.followup.send(reply[:MAX_REPLY_CHARS], ephemeral=True)
            self.stop()

        @dpy.ui.button(label="Cancel", style=dpy.ButtonStyle.secondary)
        async def _cancel(self, interaction, button):  # noqa: ANN001
            for c in self.children:
                c.disabled = True
            await interaction.response.edit_message(content="Cancelled.", view=self)
            self.stop()

    class WorkModal(dpy.ui.Modal, title="Start a 9TO5 run"):
        goal = dpy.ui.TextInput(label="Goal", style=dpy.TextStyle.paragraph, required=True, max_length=4000)
        hours = dpy.ui.TextInput(label="Hours", default="1", required=False, max_length=6)
        work_dir = dpy.ui.TextInput(label="Working directory (optional)", required=False, max_length=300)

        async def on_submit(self, interaction: "dpy.Interaction") -> None:
            view = WorkSetupView(interaction.user.id, str(self.goal),
                                 work_launcher.parseHours(str(self.hours)), str(self.work_dir) or None)
            await interaction.response.send_message(
                "Set options, then **Launch**:", view=view, ephemeral=True)

    @tree.command(name="work", description="Start a 9TO5 run (blank = guided setup)")
    @app_commands.describe(goal="What to work on (blank opens guided setup)",
                           hours="Time horizon in hours", mode="watch or gated",
                           parallel="Concurrent subtasks", no_pr="Skip the PR", work_dir="Working directory")
    @app_commands.choices(mode=[app_commands.Choice(name="watch", value="watch"),
                                app_commands.Choice(name="gated", value="gated")])
    async def work(interaction: "dpy.Interaction", goal: str | None = None, hours: float | None = None,
                   mode: "app_commands.Choice[str] | None" = None, parallel: int | None = None,
                   no_pr: bool | None = None, work_dir: str | None = None):
        if not commands.isAuthorized(interaction.user.id):
            await interaction.response.send_message("Not authorized to launch runs.", ephemeral=True)
            return
        if not goal:
            await interaction.response.send_modal(WorkModal())
            return
        await interaction.response.defer(ephemeral=True)
        req = work_launcher.WorkRequest(
            goal=goal, hours=work_launcher.parseHours(hours),
            mode=(mode.value if mode else "watch"), parallel=parallel or 1,
            no_pr=bool(no_pr), work_dir=work_dir or None)
        await interaction.followup.send(_launchOrError(req)[:MAX_REPLY_CHARS], ephemeral=True)

    @tree.error
    async def _on_app_error(interaction, error):  # noqa: ANN001  pragma: no cover
        LOG.exception("slash command error: %s", error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("internal error (see logs)", ephemeral=True)
            else:
                await interaction.response.send_message("internal error (see logs)", ephemeral=True)
        except Exception:  # noqa: BLE001
            pass

    @client.event
    async def on_ready() -> None:
        if not _synced["done"]:
            try:
                if config.DISCORD_GUILD_ID:
                    guild = dpy.Object(id=config.DISCORD_GUILD_ID)
                    tree.copy_global_to(guild=guild)
                    synced = await tree.sync(guild=guild)
                else:
                    synced = await tree.sync()
                _synced["done"] = True
                LOG.info("Command bot online as %s; synced %d slash command(s)", client.user, len(synced))
            except Exception as e:  # noqa: BLE001
                LOG.warning("slash sync failed: %s", e)

    @client.event
    async def on_interaction(interaction: "dpy.Interaction") -> None:
        # on_interaction fires for ALL interactions, in addition to the CommandTree (slash)
        # and the View store (WorkSetupView). Only the raw blocked-embed buttons below have no
        # View; everything else must be left to discord.py's own routing -- so gate BEFORE any await.
        if interaction.type != dpy.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get("custom_id", "")
        if custom_id not in ("sc_abort", "sc_skip", "sc_answer"):
            return  # View-owned (e.g. WorkSetupView) or unknown -> let discord.py route it
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            if not commands.isAuthorized(interaction.user.id):
                await interaction.followup.send("Not authorized.", ephemeral=True)
                return
            reply = handleButton(custom_id)
            await interaction.followup.send(reply[:MAX_REPLY_CHARS], ephemeral=True)
        except Exception:  # noqa: BLE001
            LOG.exception("button interaction error")

    @client.event
    async def on_message(message: "dpy.Message") -> None:
        if message.author == client.user or not message.content.strip().startswith("!"):
            return
        if not commands.isAuthorized(message.author.id):
            LOG.info("ignored '!' command from unauthorized user %s", message.author.id)
            return
        if config.DISCORD_CHANNEL_ID and message.channel.id != config.DISCORD_CHANNEL_ID:
            return
        try:
            reply = handleCommand(message.content)
        except Exception:  # noqa: BLE001
            LOG.exception("command error")
            reply = "internal error (see logs)"
        if reply:
            await message.channel.send(reply[:MAX_REPLY_CHARS])

    client.run(config.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    runCommandBot()
