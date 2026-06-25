"""Components-V2 cockpit builders -- pure, no network, no discord.py.

Builds the live "mission-control cockpit" as a plain Components-V2 tree (a list of
component dicts + the IS_COMPONENTS_V2 flag). ``buildCockpit`` is the single source
of truth consumed by BOTH transports:

  * the loop-less orchestrator (``notifications.dashboard``) POST/PATCHes the tree
    via ``discord_bot.createComponentsV2`` / ``editComponentsV2Result``;
  * the gateway wraps the same data in a ``discord.ui.LayoutView`` (``bot/ui/layouts``).

CV2 component type numbers (Discord API v10): 1=ActionRow, 2=Button, 9=Section,
10=TextDisplay, 11=Thumbnail, 12=MediaGallery, 13=File, 14=Separator, 17=Container.
A CV2 message carries NO content/embeds; ``flags`` includes bit 32768.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import config
from notifications import branding
from notifications import discord_bot as discord

# Canonical phase -> emoji (shared with the legacy dashboard title).
PHASE_EMOJI = {
    "starting": "🚀", "resuming": "↻", "architecting": "📐", "planning": "🗺️",
    "executing": "⚙️", "verifying": "🔎", "replanning": "🔁", "paused": "⏸️",
    "blocked": "🚨", "complete": "✅", "aborted": "🛑", "failed": "❌",
}

# ---- component constructors -------------------------------------------------
def container(children: list, accent: Optional[int] = None, spoiler: bool = False) -> dict:
    c: dict = {"type": 17, "components": children}
    if accent is not None:
        c["accent_color"] = accent
    if spoiler:
        c["spoiler"] = True
    return c


def text(content: str) -> dict:
    return {"type": 10, "content": str(content)}


def separator(divider: bool = True, spacing: int = 1) -> dict:
    return {"type": 14, "divider": divider, "spacing": spacing}


def section(children: list, accessory: dict) -> dict:
    """A Section: 1-3 text children + one accessory (Thumbnail or Button)."""
    return {"type": 9, "components": children[:3], "accessory": accessory}


def thumbnail(url: str, description: Optional[str] = None) -> dict:
    t: dict = {"type": 11, "media": {"url": url}}
    if description:
        t["description"] = description
    return t


def media_gallery(urls: list) -> dict:
    return {"type": 12, "items": [{"media": {"url": u}} for u in urls]}


def action_row(components: list) -> dict:
    return {"type": 1, "components": components}


# ---- duration helpers (pure; mirror dashboard's, kept local to avoid a cycle) ----
def elapsedStr(started_at) -> str:
    if not started_at:
        return "—"
    try:
        start = datetime.fromisoformat(str(started_at))
        now = datetime.now(start.tzinfo) if start.tzinfo else datetime.now()
        secs = max(0, int((now - start).total_seconds()))
    except Exception:  # noqa: BLE001
        return "—"
    h, rem = divmod(secs, 3600)
    mins = rem // 60
    if h:
        return f"{h}h {mins}m"
    if mins:
        return f"{mins}m"
    return f"{secs}s"


def etaStr(started_at, done: int, total: int) -> str:
    remaining = total - done
    if remaining <= 0 or done <= 0 or not started_at:
        return "—"
    try:
        start = datetime.fromisoformat(str(started_at))
        now = datetime.now(start.tzinfo) if start.tzinfo else datetime.now()
        elapsed = (now - start).total_seconds()
    except Exception:  # noqa: BLE001
        return "—"
    if elapsed <= 0:
        return "—"
    eta = int((elapsed / done) * remaining)
    h, rem = divmod(eta, 3600)
    mins = rem // 60
    if h:
        return f"~{h}h {mins}m"
    if mins:
        return f"~{mins}m"
    return f"~{eta}s"


# ---- the cockpit ------------------------------------------------------------
def buildCockpit(state, phase: str, *, events: Optional[list] = None,
                 model: Optional[str] = None, effort: str = "default",
                 image_url: Optional[str] = None) -> tuple[list, int]:
    """Return ``(components, flags)`` for the live cockpit. ``state`` is a TaskState;
    ``events`` is the recent-event ring (list of pre-formatted strings); ``image_url`` is an
    optional ``attachment://name.png`` reference for a Pillow chart hero (Tier 3)."""
    m = dict(state.meta)
    subtasks = [dict(s) for s in state.subtasks]
    notifs = list(state.data.get("notifications", []))
    advs = len(state.data.get("adversary_reviews", []))

    done = sum(1 for s in subtasks if s.get("status") == "done")
    total = sum(1 for s in subtasks if s.get("status") != "removed") or 1
    replans = sum(1 for n in notifs if n.get("kind") == "replan")

    current = next((s for s in subtasks if s.get("status") == "in_progress"), None)
    if current is None:
        current = next((s for s in subtasks if s.get("status") == "pending"), None)
    attempt_hint = f"  (attempt {current['attempts']})" if current and current.get("attempts") else ""
    cur_txt = f"`{current['subtask_id']}` {current['title']}{attempt_hint}" if current else "—"

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

    emoji = PHASE_EMOJI.get(phase, "🛰")
    accent = discord.statusColor(m.get("status"))
    goal = discord.truncate(m.get("goal_raw", ""), 280)

    children: list = [
        text(f"## {emoji} 9TO5 · {phase}"),
        text(f"**{goal}**"),
        separator(),
        text(f"{discord.progressBar(done, total)}\n{discord.subtaskTracker(subtasks)}"),
    ]

    if image_url:
        children.append(media_gallery([image_url]))

    children.append(separator())
    children.append(text(
        f"**Current** {cur_txt}\n"
        f"**Model** `{model or config.PRIMARY_MODEL}`  ·  **Mode** `{m.get('control_mode', 'watch')}`"
        f"  ·  **Effort** {discord.effortBar(effort)}\n"
        f"**Elapsed** {elapsedStr(m.get('started_at'))}  ·  **ETA** {etaStr(m.get('started_at'), done, total)}"
        f"  ·  🔁 {replans}  ·  ⚔️ {advs}\n"
        f"**Last verify** {verify_txt}\n"
        f"**Working dir** `{discord.truncate(m.get('work_dir') or '—', 160)}`"
    ))

    ev = events or []
    children.append(separator())
    children.append(text("**Recent events**\n" + (discord.truncate("\n".join(ev[-8:]) or "—", 1400))))

    # Control buttons live INSIDE the container (reuses the cp_* custom_ids the
    # persistent ControlPanelView already routes).
    children.append(separator())
    for row in branding.controlPanelRow():
        children.append(row)

    return [container(children, accent=accent)], config.DISCORD_MSGFLAG_COMPONENTS_V2
