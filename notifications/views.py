"""discord.py UI components for the 9TO5 gateway: persistent control-panel + blocked
views, a confirm dialog, a paginator, and the /work onboarding modal+view. Imports
discord.py (gateway-only) but is import-safe without a live connection."""
from __future__ import annotations

import discord

import config
from control import ControlBus
from notifications import audit, commands, work_launcher

LOG = config.getLogger("views")
MAX_REPLY = config.DISCORD_MAX_CONTENT - 100


def _ownerOk(interaction: "discord.Interaction") -> bool:
    return commands.isAuthorized(interaction.user.id)


async def _applyControl(interaction: "discord.Interaction", name: str, arg: str = "",
                        *, already_responded: bool = False) -> None:
    """Shared path for control-panel + blocked buttons: authorize -> audit -> spine."""
    meta = commands.COMMAND_REGISTRY.get(name, {})
    if meta.get("mutating") and not _ownerOk(interaction):
        return await _send(interaction, "Not authorized.", already_responded)
    state = commands.resolveTargetTask()
    if state is None:
        return await _send(interaction, commands.NO_TASK, already_responded)
    if meta.get("mutating"):
        audit.record(interaction.user.id, name, state.task_id, "button")
    msg = commands.applyCommand(ControlBus(state.task_id), state, commands.Command(name, arg))
    await _send(interaction, msg[:MAX_REPLY], already_responded)


async def _send(interaction: "discord.Interaction", msg: str, already_responded: bool) -> None:
    if already_responded:
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


async def _skipCurrent(interaction: "discord.Interaction", source: str) -> None:
    if not _ownerOk(interaction):
        return await interaction.response.send_message("Not authorized.", ephemeral=True)
    state = commands.resolveTargetTask()
    if state is None:
        return await interaction.response.send_message(commands.NO_TASK, ephemeral=True)
    # The backend only skips PENDING subtasks (an in_progress one has already started and cannot be
    # yanked mid-flight -- orchestrator drops a skip of a non-pending subtask). Target the next pending
    # subtask, mirroring the /skip autocomplete, so the button actually skips work instead of silently
    # no-opping on the in_progress one.
    cur = next((s for s in state.subtasks if s["status"] == "pending"), None)
    if not cur:
        return await interaction.response.send_message("No pending subtask to skip.", ephemeral=True)
    audit.record(interaction.user.id, "skip", state.task_id, source)
    msg = commands.applyCommand(ControlBus(state.task_id), state,
                                commands.Command("skip", cur["subtask_id"]))
    await interaction.response.send_message(msg[:MAX_REPLY], ephemeral=True)


class ConfirmView(discord.ui.View):
    """Ephemeral Confirm/Cancel; caller awaits .wait() then checks .value."""
    def __init__(self, owner_id: int):
        super().__init__(timeout=30)
        self.owner_id = owner_id
        self.value = False

    async def interaction_check(self, interaction: "discord.Interaction") -> bool:
        return interaction.user.id == self.owner_id

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):  # noqa: ANN001
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):  # noqa: ANN001
        self.value = False
        await interaction.response.defer()
        self.stop()


async def confirmDestructive(interaction: "discord.Interaction", label: str) -> bool:
    """Send an ephemeral confirm dialog (this consumes the initial response). True if confirmed."""
    view = ConfirmView(interaction.user.id)
    await interaction.response.send_message(f"Confirm **{label}**?", view=view, ephemeral=True)
    await view.wait()
    return view.value


# custom_id -> icon concept; applied dynamically so buttons carry the professional app-emoji icon.
_BTN_ICON = {"cp_pause": "paused", "cp_resume": "resume", "cp_approve": "approve",
             "cp_reject": "reject", "cp_skip": "skip", "cp_abort": "abort",
             "sc_answer": "info", "sc_skip": "skip", "sc_abort": "abort"}


def _applyButtonIcons(view) -> None:
    """Set each button's emoji to the custom app-emoji icon (best-effort; no-op if unprovisioned)."""
    from notifications import icons
    for c in view.children:
        cid = getattr(c, "custom_id", None)
        em = icons.buttonEmoji(_BTN_ICON.get(cid, "")) if cid else None
        if em:
            c.emoji = discord.PartialEmoji(name=em["name"], id=int(em["id"]))


class ControlPanelView(discord.ui.View):
    """Persistent (timeout=None). Matched to the dashboard message by custom_id;
    add_view'd on startup so clicks work across restarts and cross-process messages."""
    def __init__(self):
        super().__init__(timeout=None)
        _applyButtonIcons(self)

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.primary, custom_id="cp_pause")
    async def pause(self, interaction, button):  # noqa: ANN001
        await _applyControl(interaction, "pause")

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.success, custom_id="cp_resume")
    async def resume(self, interaction, button):  # noqa: ANN001
        await _applyControl(interaction, "resume")

    @discord.ui.button(label="Abort", style=discord.ButtonStyle.danger, custom_id="cp_abort")
    async def abort(self, interaction, button):  # noqa: ANN001
        if not _ownerOk(interaction):
            return await interaction.response.send_message("Not authorized.", ephemeral=True)
        if await confirmDestructive(interaction, "abort the run"):
            await _applyControl(interaction, "abort", already_responded=True)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="cp_approve")
    async def approve(self, interaction, button):  # noqa: ANN001
        await _applyControl(interaction, "approve")

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.secondary, custom_id="cp_reject")
    async def reject(self, interaction, button):  # noqa: ANN001
        await _applyControl(interaction, "reject")

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, custom_id="cp_skip")
    async def skip(self, interaction, button):  # noqa: ANN001
        await _skipCurrent(interaction, "control-panel")


class BlockedView(discord.ui.View):
    """Persistent view for the BLOCKED embed's Answer/Skip/Abort buttons (custom_ids sc_*)."""
    def __init__(self):
        super().__init__(timeout=None)
        _applyButtonIcons(self)

    @discord.ui.button(label="Answer", style=discord.ButtonStyle.primary, custom_id="sc_answer")
    async def answer(self, interaction, button):  # noqa: ANN001
        await interaction.response.send_message(
            "Type your answer as a normal message; the orchestrator will pick it up.", ephemeral=True)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, custom_id="sc_skip")
    async def skip(self, interaction, button):  # noqa: ANN001
        await _skipCurrent(interaction, "blocked")

    @discord.ui.button(label="Abort", style=discord.ButtonStyle.danger, custom_id="sc_abort")
    async def abort(self, interaction, button):  # noqa: ANN001
        if not _ownerOk(interaction):
            return await interaction.response.send_message("Not authorized.", ephemeral=True)
        if await confirmDestructive(interaction, "abort the run"):
            await _applyControl(interaction, "abort", already_responded=True)


class Paginator(discord.ui.View):
    """Prev/Next over pre-built discord.Embed pages, bound to the invoking user."""
    def __init__(self, owner_id: int, pages: list, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.pages = pages or [discord.Embed(description="(empty)")]
        self.i = 0
        self._sync()

    def _sync(self) -> None:
        self.prev.disabled = self.i <= 0
        self.next.disabled = self.i >= len(self.pages) - 1

    async def interaction_check(self, interaction: "discord.Interaction") -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Not your paginator.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="‹ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction, button):  # noqa: ANN001
        self.i = max(0, self.i - 1)
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.i], view=self)

    @discord.ui.button(label="Next ›", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, button):  # noqa: ANN001
        self.i = min(len(self.pages) - 1, self.i + 1)
        self._sync()
        await interaction.response.edit_message(embed=self.pages[self.i], view=self)


class WorkSetupView(discord.ui.View):
    """Dropdowns + Launch/Cancel for the /work guided setup (used after WorkModal)."""
    def __init__(self, owner_id: int, goal: str, hours: float, work_dir: "str | None"):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.req = work_launcher.WorkRequest(goal=goal, hours=hours, work_dir=work_dir or None)

    async def interaction_check(self, interaction: "discord.Interaction") -> bool:
        if not commands.isAuthorized(interaction.user.id):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return False
        return True

    @discord.ui.select(placeholder="Control mode", options=[
        discord.SelectOption(label="watch (autonomous + abort)", value="watch", default=True),
        discord.SelectOption(label="gated (approve plan + PR)", value="gated"),
    ])
    async def _mode(self, interaction, select):  # noqa: ANN001
        self.req.mode = select.values[0]
        await interaction.response.defer()

    @discord.ui.select(placeholder="Parallelism", options=[
        discord.SelectOption(label=f"{i} concurrent subtask(s)", value=str(i), default=(i == 1))
        for i in range(1, work_launcher.MAX_PARALLEL + 1)
    ])
    async def _parallel(self, interaction, select):  # noqa: ANN001
        self.req.parallel = int(select.values[0])
        await interaction.response.defer()

    @discord.ui.select(placeholder="Pull request", options=[
        discord.SelectOption(label="Create a PR when done", value="pr", default=True),
        discord.SelectOption(label="Skip PR", value="nopr"),
    ])
    async def _pr(self, interaction, select):  # noqa: ANN001
        self.req.no_pr = (select.values[0] == "nopr")
        await interaction.response.defer()

    @discord.ui.select(placeholder="Night mode", options=[
        discord.SelectOption(label="Night mode: off (default)", value="off", default=True),
        discord.SelectOption(label="Night mode: on (zero interaction)", value="on"),
    ])
    async def _night_mode(self, interaction, select):  # noqa: ANN001
        self.req.night_mode = (select.values[0] == "on")
        await interaction.response.defer()

    @discord.ui.button(label="Launch", style=discord.ButtonStyle.success)
    async def _launch(self, interaction, button):  # noqa: ANN001
        import asyncio
        import config as _cfg
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="Launching…", view=self)

        # Reject a duplicate launch BEFORE the ChatGPT pre-flight (which opens the shared profile and
        # kills the active run's second-brain browser). The active-run guard otherwise lives only in
        # launchOrError, after the pre-flight has already disrupted the running run.
        if work_launcher.activeRun() is not None:
            await interaction.followup.send(
                "⚠️ A run is already active. Abort it with `/abort` before starting another.",
                ephemeral=True)
            self.stop()
            return

        if _cfg.BROWSER_LAYER_ENABLED:
            from agents import browser_executor
            await interaction.followup.send(
                "Checking ChatGPT login — if a browser opens, **log in** (I'll detect it). "
                "Waiting up to 5 minutes…", ephemeral=True)
            logged_in = await asyncio.to_thread(browser_executor.preflightLogin, 300, 3)
            if not logged_in:
                await interaction.followup.send(
                    "ChatGPT login timed out (5 min). Run aborted — re-run `/work` after logging in.",
                    ephemeral=True)
                self.stop()
                return
            await interaction.followup.send("ChatGPT logged in. Starting run…", ephemeral=True)

        audit.record(interaction.user.id, "work", None, "modal")
        reply = await asyncio.to_thread(work_launcher.launchOrError, self.req)
        await interaction.followup.send(reply[:MAX_REPLY], ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def _cancel(self, interaction, button):  # noqa: ANN001
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="Cancelled.", view=self)
        self.stop()


class WipeSetupView(discord.ui.View):
    """Multi-select wipe config view. Shown immediately after /wipe."""
    def __init__(self, owner_id: int):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.selected_keys: list[str] = []
        self.backup = False

    async def interaction_check(self, interaction: "discord.Interaction") -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Not your wipe dialog.", ephemeral=True)
            return False
        return True

    @discord.ui.select(
        placeholder="Select categories to wipe…",
        min_values=0,
        max_values=8,
        options=[
            discord.SelectOption(label="Tasks", value="tasks",
                                 description="Task JSON files (state/tasks/)"),
            discord.SelectOption(label="Control Files", value="control",
                                 description="Control bus files (state/control/)"),
            discord.SelectOption(label="Experience DB", value="experience",
                                 description="experience.db + audit + trust logs"),
            discord.SelectOption(label="Obsidian Vault", value="vault",
                                 description="vault/ directory"),
            discord.SelectOption(label="Logs", value="logs",
                                 description="logs/ directory"),
            discord.SelectOption(label="Learning", value="learning",
                                 description="learning/ directory"),
            discord.SelectOption(label="Knowledge Base", value="knowledge",
                                 description="knowledge/ directory"),
            discord.SelectOption(label="ChatGPT Profile", value="chatgpt_profile",
                                 description="ChatGPT browser profile (state/chatgpt_profile/)"),
        ],
    )
    async def _categories(self, interaction: "discord.Interaction", select: "discord.ui.Select"):  # noqa: ANN001
        self.selected_keys = list(select.values)
        await interaction.response.defer()

    @discord.ui.select(
        placeholder="Backup before wipe?",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="No backup", value="no", default=True),
            discord.SelectOption(label="Backup first (tar.gz)", value="yes"),
        ],
    )
    async def _backup(self, interaction: "discord.Interaction", select: "discord.ui.Select"):  # noqa: ANN001
        self.backup = (select.values[0] == "yes")
        await interaction.response.defer()

    @discord.ui.button(label="Proceed to Confirm", style=discord.ButtonStyle.danger)
    async def _proceed(self, interaction: "discord.Interaction", button: "discord.ui.Button"):  # noqa: ANN001
        if not self.selected_keys:
            return await interaction.response.send_message(
                "No categories selected — pick at least one.", ephemeral=True)
        from wipe import CATEGORIES
        items = [CATEGORIES[k]["label"] for k in self.selected_keys if k in CATEGORIES]
        backup_note = " + backup" if self.backup else ""
        summary = "\n".join(f"• {i}" for i in items)
        await interaction.response.send_message(
            f"**Confirm wipe{backup_note}:**\n{summary}\n\nThis cannot be undone.",
            view=WipeConfirmView(self.owner_id, self.selected_keys, self.backup),
            ephemeral=True,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def _cancel(self, interaction: "discord.Interaction", button: "discord.ui.Button"):  # noqa: ANN001
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="Wipe cancelled.", view=self)
        self.stop()


class WipeConfirmView(discord.ui.View):
    """Final confirm/cancel for a wipe. Executes then restarts the bot."""
    def __init__(self, owner_id: int, keys: list[str], backup: bool):
        super().__init__(timeout=60)
        self.owner_id = owner_id
        self.keys = keys
        self.backup = backup

    async def interaction_check(self, interaction: "discord.Interaction") -> bool:
        return interaction.user.id == self.owner_id

    @discord.ui.button(label="Confirm Wipe", style=discord.ButtonStyle.danger)
    async def _confirm(self, interaction: "discord.Interaction", button: "discord.ui.Button"):  # noqa: ANN001
        import asyncio
        from wipe import executeWipe, restartBot

        await interaction.response.defer(ephemeral=True)
        results = await asyncio.to_thread(executeWipe, self.keys, self.backup)
        lines = "\n".join(v for v in results.values())
        await interaction.followup.send(
            f"**Wipe complete:**\n{lines}\n\nRestarting bot…", ephemeral=True)
        self.stop()
        await asyncio.sleep(1)
        restartBot()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def _cancel(self, interaction: "discord.Interaction", button: "discord.ui.Button"):  # noqa: ANN001
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content="Wipe cancelled.", view=self)
        self.stop()


class WorkModal(discord.ui.Modal, title="Start a 9TO5 run"):
    goal = discord.ui.TextInput(label="Goal", style=discord.TextStyle.paragraph,
                                required=True, max_length=4000)
    hours = discord.ui.TextInput(label="Hours", default="1", required=False, max_length=6)
    work_dir = discord.ui.TextInput(label="Working directory (optional)", required=False, max_length=300)

    async def on_submit(self, interaction: "discord.Interaction") -> None:
        view = WorkSetupView(interaction.user.id, str(self.goal),
                             work_launcher.parseHours(str(self.hours)), str(self.work_dir) or None)
        await interaction.response.send_message("Set options, then **Launch**:", view=view, ephemeral=True)
