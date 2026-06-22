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

from datetime import datetime, timezone
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

# effort internal key -> human display label
_EFFORT_LABELS = {
    "low": "Low", "default": "Standard", "medium": "Standard",
    "high": "High", "xhigh": "Very High", "ultracode": "Max",
}


def _nowIso() -> str:
    """Native embed timestamp (RFC3339, UTC)."""
    return datetime.now(timezone.utc).isoformat()


# =====================================================================
# UI kit
# =====================================================================
def humanPing() -> str:
    """`<@id>` mention for the human, ONLY used on severe events. '' if unset."""
    return f"<@{config.DISCORD_HUMAN_USER_ID}>" if config.DISCORD_HUMAN_USER_ID else ""


def progressBar(done: int, total: int, width: int = 12) -> str:
    total = max(int(total), 1)
    done = max(0, min(int(done), total))
    pct = int(round(100 * done / total))
    filled = int(round(width * done / total))
    bar = f"{'▰' * filled}{'▱' * (width - filled)}"
    return f"{bar}  {pct:>3}%  ({done}/{total})"


def subtaskTracker(subtasks: list[dict], limit: int = 12) -> str:
    n_done = sum(1 for s in subtasks if s.get("status") == "done")
    n_running = sum(1 for s in subtasks if s.get("status") == "in_progress")
    n_failed = sum(1 for s in subtasks if s.get("status") == "failed")
    n_pending = len(subtasks) - n_done - n_running - n_failed
    return f"✅ {n_done}  ⚡ {n_running}  ⬜ {max(n_pending, 0)}  ❌ {n_failed}"


def effortBar(effort: Optional[str]) -> str:
    key = (effort or "default").lower()
    bar = config.EFFORT_BARS.get(key, config.EFFORT_BARS["default"])
    label = _EFFORT_LABELS.get(key, "Standard")
    return f"{bar}  {label}"


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
def _goalSummary(goal: str, limit: int = 320) -> str:
    """First sentence(s) of the goal up to ~limit chars, so the embed leads with the gist
    instead of dumping the whole multi-line paragraph."""
    g = " ".join((goal or "").split())  # collapse whitespace/newlines
    if len(g) <= limit:
        return g or "—"
    cut = g[:limit]
    dot = cut.rfind(". ")
    if dot >= limit * 0.5:            # prefer a clean sentence break if one is reasonably late
        return cut[:dot + 1]
    return cut.rsplit(" ", 1)[0] + "…"


def planningStartEmbed(goal: str, subtasks) -> dict:
    """Structured plan embed. ``subtasks`` may be a list of subtask dicts (preferred -- renders the
    titles as a numbered checklist) or a bare int count (back-compat)."""
    if isinstance(subtasks, int):
        items, count = [], subtasks
    else:
        items = list(subtasks or [])
        count = len(items)
    lines = []
    for i, st in enumerate(items[:12], 1):
        title = str((st.get("title") if isinstance(st, dict) else st) or f"subtask {i}").strip()
        lines.append(f"`{i:>2}.` {title[:140]}")
    if len(items) > 12:
        lines.append(f"…and {len(items) - 12} more")
    plan_block = "\n".join(lines) if lines else "_authoring subtasks…_"
    plural = "s" if count != 1 else ""
    description = (
        f"**🎯 Goal**\n{_goalSummary(goal)}\n\n"
        f"**🗺️ Plan — {count} subtask{plural}**\n{plan_block}"
    )
    return {
        "title": "🗺️ Plan ready",
        "color": statusColor("planning"),
        "description": description[:4000],
        "timestamp": _nowIso(),
        "fields": [
            {"name": "Subtasks", "value": str(count), "inline": True},
            {"name": "Next", "value": "execution starting", "inline": True},
        ],
    }


def architectDoneEmbed(doc_path: str) -> dict:
    return {
        "title": "🔵 Architecture complete",
        "color": statusColor("architecting"),
        "timestamp": _nowIso(),
        "fields": [{"name": "Design doc", "value": f"`{doc_path}`"}],
    }


def adversaryTriggeredEmbed(subtask_title: str, reason: str, verdict: Optional[str] = None) -> dict:
    v = (verdict or "").lower()
    challenged = v in ("challenged", "rejected", "reject", "blocked", "fail")
    color = statusColor("blocked") if challenged else statusColor("done")
    if verdict is None:
        color = statusColor("adversary")
    fields = [
        {"name": "Subtask", "value": subtask_title[:1000]},
        {"name": "Trigger", "value": reason[:1000]},
    ]
    if verdict is not None:
        fields.append({"name": "Verdict", "value": formatVerdict(verdict), "inline": True})
    return {
        "title": "⚔️ Adversary review",
        "color": color,
        "timestamp": _nowIso(),
        "fields": fields,
    }


def blockedEmbed(reason: str, question: Optional[str] = None) -> dict:
    desc = f"**{reason[:1500]}**"
    if question:
        quoted = "\n".join(f"> {line}" for line in question[:1500].splitlines() or [""])
        desc += f"\n\nClaude Code is asking:\n{quoted}"
    return {
        "title": "🚨 BLOCKED — human decision required",
        "color": statusColor("blocked"),
        "description": desc[:4000],
        "timestamp": _nowIso(),
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

    subtasks_val = f"{done}/{total}" + (f"  ({failed} failed)" if failed else "")
    pr = (pr_link or "").strip()
    pr_val = f"[Open PR]({pr})" if pr.lower().startswith("http") else (pr or "—")

    desc = (
        f"**{state.meta['goal_raw'][:280]}**\n"
        f"{progressBar(done, total)}"
    )
    return {
        "title": "✅ 9TO5 — run complete",
        "color": statusColor(state.meta.get("status")),
        "description": desc[:4000],
        "timestamp": _nowIso(),
        "fields": [
            {"name": "Subtasks", "value": subtasks_val, "inline": True},
            {"name": "Time elapsed", "value": elapsed or "—", "inline": True},
            {"name": "Replans", "value": str(replans), "inline": True},
            {"name": "Adversary", "value": str(advs), "inline": True},
            {"name": "Progress", "value": subtaskTracker(state.subtasks), "inline": False},
            {"name": "Pull request", "value": pr_val, "inline": False},
        ],
        "footer": {"text": f"task {state.task_id[:8]}"},
    }


def sendBlocked(reason: str, question: Optional[str] = None) -> dict:
    """Severe: new message, @everyone + human ping, with Answer/Skip/Abort buttons."""
    content = ("@everyone " + humanPing()).strip()
    return sendEmbed(blockedEmbed(reason, question), content=content, components=blockedComponents())
