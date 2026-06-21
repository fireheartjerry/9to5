"""Discord notifications -- professional, glass-box embeds + REST plumbing.

Two halves:
  * REST helpers (create/edit/fetch/pin messages, send embeds with components) +
    a kit of UI builders (progress bars, subtask trackers, effort indicators,
    status-colored sidebars, relative timestamps, dramatic blocked embed with
    Answer/Skip/Abort buttons, divider'd completion summary).
  * runCommandBot lives in notifications.command_bot now (the rich gateway).

Design rules (per spec): ONE persistent pinned dashboard that edits in-place
(see notifications.dashboard); only BLOCKED and COMPLETE send new messages with
pings. The human (DISCORD_HUMAN_USER_ID) is @-pinged ONLY for severe events.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import requests

import config

LOG = config.getLogger("discord")

_API = "https://discord.com/api/v10"

GREEN = 0x2ECC71
BLUE = 0x3498DB
ORANGE = 0xE67E22
RED = 0xE74C3C
PURPLE = 0x9B59B6
YELLOW = 0xF1C40F
DIVIDER = "━━━━━━━━━━━━━━━━━━━━━"

_STATUS_MARK = {"done": "✅", "in_progress": "⚡", "failed": "❌", "removed": "⏭️", "pending": "⬜"}


# =====================================================================
# UI kit
# =====================================================================
def humanPing() -> str:
    """`<@id>` mention for the human, ONLY used on severe events. '' if unset."""
    return f"<@{config.DISCORD_HUMAN_USER_ID}>" if config.DISCORD_HUMAN_USER_ID else ""


def progressBar(done: int, total: int, width: int = 16) -> str:
    total = max(int(total), 1)
    done = max(0, min(int(done), total))
    pct = int(round(100 * done / total))
    filled = int(round(width * done / total))
    return f"[{'█' * filled}{'░' * (width - filled)}] {pct}%"


def subtaskTracker(subtasks: list[dict], limit: int = 12) -> str:
    items = subtasks[:limit]
    out = " ".join(f"{_STATUS_MARK.get(s['status'], '⬜')} {s['subtask_id']}" for s in items)
    if len(subtasks) > limit:
        out += f"  +{len(subtasks) - limit}"
    return out or "—"


def effortBar(effort: Optional[str]) -> str:
    key = (effort or "default").lower()
    bar = config.EFFORT_BARS.get(key, config.EFFORT_BARS["default"])
    return f"EFFORT {bar} {effort or 'default'}"


def statusColor(status: Optional[str]) -> int:
    return config.STATUS_COLORS.get(status or "", 0x95A5A6)


def relTime(value=None) -> str:
    """Discord native relative timestamp: <t:UNIX:R>."""
    try:
        if value is None:
            ts = int(datetime.now().timestamp())
        elif isinstance(value, (int, float)):
            ts = int(value)
        else:
            ts = int(datetime.fromisoformat(str(value)).timestamp())
    except Exception:  # noqa: BLE001
        ts = int(datetime.now().timestamp())
    return f"<t:{ts}:R>"


def formatVerdict(verdict: Optional[str]) -> str:
    v = (verdict or "").lower()
    return "⚔️ CHALLENGED" if v in ("challenged", "rejected", "reject", "blocked", "fail") else "✅ APPROVED"


# =====================================================================
# REST plumbing
# =====================================================================
def _authHeaders() -> dict:
    return {"Authorization": f"Bot {config.DISCORD_BOT_TOKEN}", "Content-Type": "application/json"}


def _post(payload: dict) -> dict:
    if not config.DISCORD_BOT_TOKEN or not config.DISCORD_CHANNEL_ID:
        LOG.warning("Discord not configured; skipping send")
        return {"ok": False, "reason": "not-configured"}
    url = f"{_API}/channels/{config.DISCORD_CHANNEL_ID}/messages"
    try:
        r = requests.post(url, json=payload, headers=_authHeaders(), timeout=15)
        ok = 200 <= r.status_code < 300
        if not ok:
            LOG.warning("Discord send -> %s: %s", r.status_code, r.text[:200])
        return {"ok": ok, "status": r.status_code, "body": r.text[:300]}
    except Exception as e:  # noqa: BLE001
        LOG.warning("Discord send failed: %s", e)
        return {"ok": False, "reason": str(e)}


def createMessage(embed: dict, content: Optional[str] = None, components: Optional[list] = None) -> Optional[str]:
    if not config.DISCORD_BOT_TOKEN or not config.DISCORD_CHANNEL_ID:
        return None
    url = f"{_API}/channels/{config.DISCORD_CHANNEL_ID}/messages"
    payload: dict = {"embeds": [embed]}
    if content:
        payload["content"] = content
        payload["allowed_mentions"] = {"parse": ["everyone", "users"]}
    if components:
        payload["components"] = components
    try:
        r = requests.post(url, json=payload, headers=_authHeaders(), timeout=15)
        if 200 <= r.status_code < 300:
            return str(r.json().get("id"))
        LOG.warning("createMessage -> %s: %s", r.status_code, r.text[:200])
    except Exception as e:  # noqa: BLE001
        LOG.warning("createMessage failed: %s", e)
    return None


def editMessage(message_id: str, embed: dict, content: Optional[str] = None,
                components: Optional[list] = None) -> bool:
    if not message_id or not config.DISCORD_BOT_TOKEN or not config.DISCORD_CHANNEL_ID:
        return False
    url = f"{_API}/channels/{config.DISCORD_CHANNEL_ID}/messages/{message_id}"
    payload: dict = {"embeds": [embed]}
    if content is not None:
        payload["content"] = content
    if components is not None:
        payload["components"] = components
    try:
        r = requests.patch(url, json=payload, headers=_authHeaders(), timeout=15)
        return 200 <= r.status_code < 300
    except Exception as e:  # noqa: BLE001
        LOG.warning("editMessage failed: %s", e)
        return False


def pinMessage(message_id: Optional[str]) -> bool:
    if not message_id or not config.DISCORD_BOT_TOKEN or not config.DISCORD_CHANNEL_ID:
        return False
    url = f"{_API}/channels/{config.DISCORD_CHANNEL_ID}/pins/{message_id}"
    try:
        r = requests.put(url, headers=_authHeaders(), timeout=15)
        return 200 <= r.status_code < 300
    except Exception as e:  # noqa: BLE001
        LOG.warning("pinMessage failed: %s", e)
        return False


def fetchMessagesAfter(after_id: Optional[str], limit: int = 25) -> tuple[list[dict], Optional[str]]:
    if not config.DISCORD_BOT_TOKEN or not config.DISCORD_CHANNEL_ID:
        return [], after_id
    url = f"{_API}/channels/{config.DISCORD_CHANNEL_ID}/messages"
    params: dict = {"limit": limit}
    if after_id:
        params["after"] = after_id
    try:
        r = requests.get(url, params=params, headers=_authHeaders(), timeout=15)
        if not (200 <= r.status_code < 300):
            return [], after_id
        msgs = r.json()
        out = [{"id": str(m.get("id")), "content": m.get("content") or "",
                "author_is_bot": bool((m.get("author") or {}).get("bot"))} for m in reversed(msgs)]
        latest = out[-1]["id"] if out else after_id
        return out, latest
    except Exception as e:  # noqa: BLE001
        LOG.warning("fetchMessagesAfter failed: %s", e)
        return [], after_id


def sendEmbed(embed: dict, content: Optional[str] = None, components: Optional[list] = None) -> dict:
    payload: dict = {"embeds": [embed]}
    if content:
        payload["content"] = content
        payload["allowed_mentions"] = {"parse": ["everyone", "users"]}
    if components:
        payload["components"] = components
    return _post(payload)


# =====================================================================
# Embed builders
# =====================================================================
def planningStartEmbed(goal: str, subtask_count: int) -> dict:
    return {
        "title": "🟢 Planning started",
        "color": BLUE,
        "fields": [
            {"name": "Goal", "value": goal[:1000] or "-"},
            {"name": "Subtasks", "value": str(subtask_count), "inline": True},
            {"name": "When", "value": relTime(), "inline": True},
        ],
    }


def architectDoneEmbed(doc_path: str) -> dict:
    return {
        "title": "🔵 Architecture complete",
        "color": BLUE,
        "fields": [{"name": "architect.md", "value": doc_path},
                   {"name": "When", "value": relTime(), "inline": True}],
    }


def adversaryTriggeredEmbed(subtask_title: str, reason: str, verdict: Optional[str] = None) -> dict:
    fields = [
        {"name": "Subtask", "value": subtask_title[:1000]},
        {"name": "Trigger", "value": reason[:1000]},
    ]
    if verdict is not None:
        fields.append({"name": "Verdict", "value": formatVerdict(verdict), "inline": True})
    return {"title": "⚔️ Adversary review", "color": ORANGE, "fields": fields}


def blockedEmbed(reason: str, question: Optional[str] = None) -> dict:
    desc = f"**{reason[:1500]}**"
    if question:
        desc += f"\n\nClaude Code is asking:\n```\n{question[:1500]}\n```"
    return {
        "title": "🚨 BLOCKED — human decision required",
        "color": RED,
        "description": desc[:4000],
        "fields": [{"name": "When", "value": relTime(), "inline": True}],
    }


def blockedComponents() -> list:
    """Action row with Answer / Skip / Abort buttons (handled by the gateway bot)."""
    return [{"type": 1, "components": [
        {"type": 2, "style": 1, "label": "Answer", "custom_id": "sc_answer", "emoji": {"name": "✍️"}},
        {"type": 2, "style": 2, "label": "Skip", "custom_id": "sc_skip", "emoji": {"name": "⏭️"}},
        {"type": 2, "style": 4, "label": "Abort", "custom_id": "sc_abort", "emoji": {"name": "🛑"}},
    ]}]


def completeEmbed(state, pr_link: str, elapsed: str) -> dict:
    done, total = state.progress()
    notifs = state.data.get("notifications", [])
    replans = sum(1 for n in notifs if n.get("kind") == "replan")
    advs = len(state.data.get("adversary_reviews", []))
    failed = sum(1 for s in state.subtasks if s["status"] == "failed")
    desc = (
        f"**Goal:** {state.meta['goal_raw'][:280]}\n{DIVIDER}\n"
        f"**Subtasks:** {progressBar(done, total)}  ({done}/{total}"
        + (f", {failed} failed" if failed else "") + ")\n"
        f"{subtaskTracker(state.subtasks)}\n{DIVIDER}\n"
        f"⏱ **Total time:** {elapsed}\n"
        f"🔁 **Replans:** {replans}    ⚔️ **Adversary triggers:** {advs}\n"
        f"{DIVIDER}\n"
        f"🔗 **PR:** {pr_link}"
    )
    return {
        "title": "✅ 9TO5 — run complete",
        "color": statusColor(state.meta.get("status")),
        "description": desc[:4000],
        "footer": {"text": f"task {state.task_id[:8]}"},
    }


def sendBlocked(reason: str, question: Optional[str] = None) -> dict:
    """Severe: new message, @everyone + human ping, with Answer/Skip/Abort buttons."""
    content = ("@everyone " + humanPing()).strip()
    return sendEmbed(blockedEmbed(reason, question), content=content, components=blockedComponents())
