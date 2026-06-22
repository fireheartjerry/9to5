"""DiscordDashboard -- ONE persistent, pinned embed that mirrors the whole run.

Created + pinned at run start, then PATCH-edited in place on every transition
(never spams new messages). Professional layout: status-colored sidebar, text
progress bar, subtask tracker, effort indicator, rich metadata (model / effort /
layer / replans / adversary triggers), and Discord-native relative timestamps.
Degrades to a silent no-op when Discord is unconfigured.
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import config
from notifications import commands
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
        self._lock = threading.Lock()   # guards mutable state under parallel workers
        self._send_lock = threading.Lock()    # serialize network PATCH/POST across workers
        self._state_lock = None                # set by start(); used to snapshot TaskState safely
        self._recreated = False                # at most one 404 recovery (no pin spam)

    def event(self, text: str) -> None:
        with self._lock:
            self.events.append(f"`{datetime.now().astimezone().strftime('%H:%M:%S')}` {text}")

    def _eventsSnapshot(self) -> list:
        with self._lock:
            return list(self.events)

    @staticmethod
    def _elapsed(started_at) -> str:
        """Human duration since started_at (e.g. '1h 23m'); '—' if unknown."""
        if not started_at:
            return "—"
        try:
            start = datetime.fromisoformat(str(started_at))
            now = datetime.now(start.tzinfo) if start.tzinfo else datetime.now()
            secs = int((now - start).total_seconds())
        except Exception:  # noqa: BLE001
            return "—"
        if secs < 0:
            secs = 0
        h, rem = divmod(secs, 3600)
        mins = rem // 60
        if h:
            return f"{h}h {mins}m"
        if mins:
            return f"{mins}m"
        return f"{secs}s"

    # ---- embed construction --------------------------------------------
    def _embed(self, state: TaskState, phase: str) -> dict:
        lock = self._state_lock
        if lock:
            lock.acquire()
        try:
            m = dict(state.meta)
            subtasks = [dict(s) for s in state.subtasks]
            notifs = list(state.data.get("notifications", []))
            advs = len(state.data.get("adversary_reviews", []))
        finally:
            if lock:
                lock.release()
        done = sum(1 for s in subtasks if s["status"] == "done")
        total = sum(1 for s in subtasks if s["status"] != "removed") or 1
        replans = sum(1 for n in notifs if n.get("kind") == "replan")

        current = next((s for s in subtasks if s["status"] == "in_progress"), None)
        if current is None:
            current = next((s for s in subtasks if s["status"] == "pending"), None)
        cur_txt = f"`{current['subtask_id']}` {current['title']}" if current else "—"

        last_v = None
        for s in subtasks:
            if s.get("verify_result"):
                last_v = (s["subtask_id"], s["verify_result"])
        if last_v:
            sid, vr = last_v
            mark = "✅" if vr.get("passed") else "❌"
            verify_txt = f"{mark} `{sid}` — `{str(vr.get('cmd') or vr.get('expect'))[:70]}`"
        else:
            verify_txt = "—"

        emoji = _PHASE_EMOJI.get(phase, "🛰")
        paused = m.get("status") == "paused"
        hint = "!resume" if paused else commands.footerHelp()
        return {
            "title": f"{emoji} 9TO5 · {phase}",
            "color": discord.statusColor(m["status"]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "description": (
                f"**{m['goal_raw'][:240]}**\n"
                f"{discord.progressBar(done, total)}\n"
                f"{discord.subtaskTracker(subtasks)}"
            ),
            "fields": [
                {"name": "Model", "value": f"`{self.model}`", "inline": True},
                {"name": "Mode", "value": f"`{m.get('control_mode', 'watch')}`", "inline": True},
                {"name": "Elapsed", "value": self._elapsed(m.get("started_at")), "inline": True},
                {"name": "🔁 Replans", "value": str(replans), "inline": True},
                {"name": "⚔️ Adversary", "value": str(advs), "inline": True},
                {"name": "Effort", "value": discord.effortBar(self.effort), "inline": True},
                {"name": "Current subtask", "value": cur_txt[:1000], "inline": False},
                {"name": "Last verify", "value": verify_txt, "inline": False},
                {"name": "Recent events", "value": ("\n".join(self._eventsSnapshot()) or "—")[:1000], "inline": False},
            ],
            "footer": {"text": f"task {state.task_id[:8]} · web :{config.WEB_DASHBOARD_PORT} · {hint}"},
        }

    # ---- lifecycle ------------------------------------------------------
    def start(self, state: TaskState, phase: str = "starting", state_lock=None) -> None:
        if not config.DISCORD_DASHBOARD:
            return
        self._state_lock = state_lock
        self.event(f"run started · mode `{state.meta.get('control_mode', 'watch')}`")
        embed = self._embed(state, phase)
        with self._send_lock:
            self.message_id = discord.createMessage(embed)
            if self.message_id:
                discord.pinMessage(self.message_id)
                LOG.info("Dashboard message %s created + pinned", self.message_id)

    def update(self, state: TaskState, phase: str, note: Optional[str] = None,
               effort: Optional[str] = None, model: Optional[str] = None) -> None:
        if not config.DISCORD_DASHBOARD:
            return
        with self._lock:
            if effort:
                self.effort = effort
            if model:
                self.model = model
        if note:
            self.event(note)
        embed = self._embed(state, phase)
        with self._send_lock:
            if self.message_id:
                ok = discord.editMessage(self.message_id, embed)
                if not ok and not self._recreated:   # dashboard likely deleted -> recreate ONCE
                    self._recreated = True
                    self.message_id = discord.createMessage(embed)
                    if self.message_id:
                        discord.pinMessage(self.message_id)
            else:
                self.message_id = discord.createMessage(embed)
                if self.message_id:
                    discord.pinMessage(self.message_id)

    def unpin(self) -> None:
        """Remove the pinned dashboard when the run ends (idempotent; never raises)."""
        if not config.DISCORD_DASHBOARD or not self.message_id:
            return
        try:
            discord.unpinMessage(self.message_id)
            LOG.info("Dashboard message %s unpinned", self.message_id)
        except Exception:  # noqa: BLE001
            LOG.warning("dashboard unpin failed", exc_info=True)
