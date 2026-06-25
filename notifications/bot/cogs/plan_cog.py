"""Tier 2 interactivity: the in-Discord plan editor, the event-timeline browser, and two
message context menus. All mutations route through the pure ``commands`` spine + ControlBus
``plan_ops`` (the orchestrator's _applyOps grew an ``edit`` op to match), and every mutating
path is owner-gated + audited -- the same contract every other surface uses.
"""
from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands as dpy_commands

from control import ControlBus
from notifications import audit
from notifications import commands as spine

import config

LOG = config.getLogger("cog.plan")


# ---- pure helpers (testable) ------------------------------------------------
def timelineLines(state) -> list:
    out = []
    for n in state.data.get("notifications", []) or []:
        at = (n.get("at") or "")[:19]
        out.append(f"`{at}` **{n.get('kind', '?')}** — {str(n.get('detail', ''))[:120]}")
    return out


def _timelinePages(state, per: int = 12) -> list:
    lines = timelineLines(state)
    if not lines:
        return [discord.Embed(title="🕰 Timeline", description="_no events yet_")]
    pages = []
    total = (len(lines) + per - 1) // per
    for i in range(0, len(lines), per):
        pages.append(discord.Embed(title=f"🕰 Timeline ({i // per + 1}/{total})",
                                   description="\n".join(lines[i:i + per])))
    return pages


# ---- plan editor UI ---------------------------------------------------------
class SubtaskEditModal(discord.ui.Modal):
    def __init__(self, sid: str, cur_title: str, cur_desc: str) -> None:
        super().__init__(title=f"Edit {sid}"[:45])
        self.sid = sid
        self.t_title = discord.ui.TextInput(label="Title", default=(cur_title or "")[:100], max_length=100)
        self.t_desc = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph,
                                           default=(cur_desc or "")[:1000], required=False, max_length=2000)
        self.add_item(self.t_title)
        self.add_item(self.t_desc)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not spine.isAuthorized(interaction.user.id):
            return await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
        state = spine.resolveTargetTask()
        if state is None:
            return await interaction.response.send_message(spine.NO_TASK, ephemeral=True)
        audit.record(interaction.user.id, "edit", state.task_id, "plan-editor")
        ControlBus(state.task_id).pushOp({"op": "edit", "subtask_id": self.sid,
                                          "title": str(self.t_title), "description": str(self.t_desc)})
        await interaction.response.send_message(f"✏️ queued edit for `{self.sid}`", ephemeral=True)


class _EditSelect(discord.ui.Select):
    def __init__(self, subtasks: list) -> None:
        opts = [discord.SelectOption(label=(s["title"] or s["subtask_id"])[:100], value=s["subtask_id"],
                                     description=f"{s['subtask_id']} · {s['status']}"[:100])
                for s in subtasks[:25]]
        super().__init__(placeholder="Pick a subtask to edit…", options=opts)

    async def callback(self, interaction: discord.Interaction) -> None:
        sid = self.values[0]
        state = spine.resolveTargetTask()
        st = state.getSubtask(sid) if state else None
        if not st:
            return await interaction.response.send_message("That subtask is gone.", ephemeral=True)
        await interaction.response.send_modal(
            SubtaskEditModal(sid, st.get("title", ""), st.get("description", "")))


class PlanEditView(discord.ui.View):
    def __init__(self, owner_id: int, subtasks: list) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.add_item(_EditSelect(subtasks))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not spine.isAuthorized(interaction.user.id):
            await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
            return False
        return True


# ---- the cog ----------------------------------------------------------------
class PlanCog(dpy_commands.Cog):
    def __init__(self, bot: dpy_commands.Bot) -> None:
        self.bot = bot
        self.ctx_goal = app_commands.ContextMenu(name="Send to Nightclaw as a goal", callback=self._goal)
        self.ctx_add = app_commands.ContextMenu(name="Add as 9to5 subtask", callback=self._addsub)
        bot.tree.add_command(self.ctx_goal)
        bot.tree.add_command(self.ctx_add)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.ctx_goal.name, type=self.ctx_goal.type)
        self.bot.tree.remove_command(self.ctx_add.name, type=self.ctx_add.type)

    @app_commands.command(name="plan-edit", description="Edit the current plan's subtasks interactively")
    async def plan_edit(self, interaction: discord.Interaction) -> None:
        if not spine.isAuthorized(interaction.user.id):
            return await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
        state = spine.resolveTargetTask()
        if state is None:
            return await interaction.response.send_message(spine.NO_TASK, ephemeral=True)
        editable = [s for s in state.subtasks if s["status"] in ("pending", "in_progress")]
        if not editable:
            return await interaction.response.send_message(
                "No editable (pending/in_progress) subtasks.", ephemeral=True)
        await interaction.response.send_message(
            "Pick a subtask to edit:", view=PlanEditView(interaction.user.id, editable), ephemeral=True)

    @app_commands.command(name="timeline", description="Browse the run's event timeline (time-travel)")
    async def timeline(self, interaction: discord.Interaction) -> None:
        state = spine.resolveTargetTask()
        if state is None:
            return await interaction.response.send_message(spine.NO_TASK, ephemeral=True)
        from notifications import views
        pages = _timelinePages(state)
        view = views.Paginator(interaction.user.id, pages) if len(pages) > 1 else None
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)

    async def _goal(self, interaction: discord.Interaction, message: discord.Message) -> None:
        if not spine.isAuthorized(interaction.user.id):
            return await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
        goal = (message.content or "").strip()
        if not goal:
            return await interaction.response.send_message("That message has no text.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        from notifications import work_launcher
        audit.record(interaction.user.id, "work", None, "ctx-menu")
        req = work_launcher.WorkRequest(goal=goal, hours=1.0)
        reply = await asyncio.to_thread(work_launcher.launchOrError, req)
        await interaction.followup.send(reply[:1800], ephemeral=True)

    async def _addsub(self, interaction: discord.Interaction, message: discord.Message) -> None:
        if not spine.isAuthorized(interaction.user.id):
            return await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
        state = spine.resolveTargetTask()
        if state is None:
            return await interaction.response.send_message(spine.NO_TASK, ephemeral=True)
        title = (message.content or "").strip()[:120]
        if not title:
            return await interaction.response.send_message("That message has no text.", ephemeral=True)
        audit.record(interaction.user.id, "add", state.task_id, "ctx-menu")
        ControlBus(state.task_id).pushOp({"op": "add", "title": title, "description": message.content[:2000]})
        await interaction.response.send_message(f"➕ queued subtask: {title}", ephemeral=True)


async def setup(bot: dpy_commands.Bot) -> None:
    await bot.add_cog(PlanCog(bot))
