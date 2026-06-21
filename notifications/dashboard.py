"""DiscordDashboard -- ONE persistent, pinned embed that mirrors the whole run.

Created + pinned at run start, then PATCH-edited in place on every transition
(never spams new messages). Professional layout: status-colored sidebar, text
progress bar, subtask tracker, effort indicator, rich metadata (model / effort /
layer / replans / adversary triggers), and Discord-native relative timestamps.
Degrades to a silent no-op when Discord is unconfigured.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Optional

import config
from notifications import discord_bot as discord
from state.task import TaskState

LOG = config.getLogger("dashboard")

# phase label -> emoji for the title
_PHASE_EMOJI = {
    "starting": "🚀", "resuming": "↻", "architecting": "📐", "planning": "🗺️",
    "executing": "⚙️", "verifying": "🔎", "replanning": "🔁", "paused": "⏸️",
    "blocked": "🚨", "complete": "✅", "aborted": "🛑", "failed": "❌",
}


class DiscordDashboard:
    def __init__(self) -> None:
        self.message_id: Optional[str] = None
        self.events: deque[str] = deque(maxlen=8)
        self.effort: str = "default"
        self.model: str = config.PRIMARY_MODEL

    def event(self, text: str) -> None:
        self.events.append(f"`{datetime.now().strftime('%H:%M:%S')}` {text}")

    # ---- embed construction --------------------------------------------
    def _embed(self, state: TaskState, phase: str) -> dict:
        m = state.meta
        done, total = state.progress()
        notifs = state.data.get("notifications", [])
        replans = sum(1 for n in notifs if n.get("kind") == "replan")
        advs = len(state.data.get("adversary_reviews", []))

        current = next((s for s in state.subtasks if s["status"] == "in_progress"), None) or state.nextActionable()
        cur_txt = f"`{current['subtask_id']}` {current['title']}" if current else "—"

        last_v = None
        for s in state.subtasks:
            if s.get("verify_result"):
                last_v = (s["subtask_id"], s["verify_result"])
        if last_v:
            sid, vr = last_v
            mark = "✅" if vr.get("passed") else "❌"
            verify_txt = f"{mark} `{sid}` — `{str(vr.get('cmd') or vr.get('expect'))[:70]}`"
        else:
            verify_txt = "—"

        emoji = _PHASE_EMOJI.get(phase, "🛰")
        return {
            "title": f"{emoji} 9TO5 · {phase}",
            "color": discord.statusColor(m["status"]),
            "description": (
                f"**{m['goal_raw'][:240]}**\n"
                f"{discord.progressBar(done, total)}  ({done}/{total})\n"
                f"{discord.subtaskTracker(state.subtasks)}"
            ),
            "fields": [
                {"name": "Effort", "value": discord.effortBar(self.effort), "inline": False},
                {"name": "Model", "value": f"`{self.model}`", "inline": True},
                {"name": "Mode / Layer", "value": f"{m.get('control_mode', 'watch')} · L3", "inline": True},
                {"name": "Status", "value": f"`{m['status']}`", "inline": True},
                {"name": "Current subtask", "value": cur_txt[:1000], "inline": False},
                {"name": "Last verify", "value": verify_txt, "inline": False},
                {"name": "🔁 Replans", "value": str(replans), "inline": True},
                {"name": "⚔️ Adversary", "value": str(advs), "inline": True},
                {"name": "Started", "value": discord.relTime(m.get("started_at")), "inline": True},
                {"name": "Deadline", "value": discord.relTime(m.get("deadline_at")), "inline": True},
                {"name": "Recent events", "value": ("\n".join(self.events) or "—")[:1000], "inline": False},
            ],
            "footer": {"text": f"task {state.task_id[:8]} · web :{config.WEB_DASHBOARD_PORT} · !status !abort !pause"},
        }

    # ---- lifecycle ------------------------------------------------------
    def start(self, state: TaskState, phase: str = "starting") -> None:
        if not config.DISCORD_DASHBOARD:
            return
        self.event(f"run started · mode `{state.meta.get('control_mode', 'watch')}`")
        self.message_id = discord.createMessage(self._embed(state, phase))
        if self.message_id:
            discord.pinMessage(self.message_id)
            LOG.info("Dashboard message %s created + pinned", self.message_id)

    def update(self, state: TaskState, phase: str, note: Optional[str] = None,
               effort: Optional[str] = None, model: Optional[str] = None) -> None:
        if not config.DISCORD_DASHBOARD:
            return
        if effort:
            self.effort = effort
        if model:
            self.model = model
        if note:
            self.event(note)
        embed = self._embed(state, phase)
        if self.message_id:
            discord.editMessage(self.message_id, embed)
        else:
            self.message_id = discord.createMessage(embed)
            if self.message_id:
                discord.pinMessage(self.message_id)
