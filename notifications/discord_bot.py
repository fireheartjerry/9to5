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

import time

import requests

import config

LOG = config.getLogger("discord")

_SESSION = requests.Session()   # persistent connection pool; reused across all REST calls

_API = "https://discord.com/api/v10"

def _nowIso() -> str:
    """Native embed timestamp (RFC3339, UTC)."""
    return datetime.now(timezone.utc).isoformat()


# =====================================================================
# UI kit
# =====================================================================
def humanPing() -> str:
    """`<@id>` mention for the human, ONLY used on severe events. '' if unset or night mode."""
    if config.NIGHT_MODE or not config.DISCORD_HUMAN_USER_ID:
        return ""
    return f"<@{config.DISCORD_HUMAN_USER_ID}>"


def progressBar(done: int, total: int, width: int = 16) -> str:
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
    countable = n_done + n_failed
    pass_rate = f"  ·  {round(100 * n_done / countable)}% pass" if countable > 0 else ""
    return f"✅ {n_done}  ⚡ {n_running}  ⬜ {max(n_pending, 0)}  ❌ {n_failed}{pass_rate}"


def effortBar(effort: Optional[str]) -> str:
    key = (effort or "default").lower()
    bar = config.EFFORT_BARS.get(key, config.EFFORT_BARS["default"])
    label = config.EFFORT_LABELS.get(key, "Standard")
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


_APPROVED = {"approved", "approve", "pass", "ok"}
_CHALLENGED = {"challenged", "rejected", "reject", "blocked", "fail"}


def formatVerdict(verdict: Optional[str]) -> str:
    v = (verdict or "").lower().strip()
    if v in _APPROVED:
        return "✅ APPROVED"
    if v in _CHALLENGED:
        return "⚔️ CHALLENGED"
    return "❔ UNKNOWN"


# =====================================================================
# REST plumbing -- one chokepoint
# =====================================================================
_DISABLED = False   # latched ON only by a hard 401 (bad token); never by 403/404
# Global 429 circuit breaker: a monotonic deadline. While now < this, EVERY REST call short-circuits
# locally (returns None without touching the network). Discord rate-limits are global to the bot, so
# without this any caller -- the 4s control poll, the dashboard PATCH, parallel workers -- keeps
# hitting a rate-limited API and deepens the ban (the same-millisecond 429 storms seen in logs). The
# chokepoint itself now enforces the backoff so no caller can hammer regardless of its loop cadence.
_RATE_LIMITED_UNTIL = 0.0
_RL_COOLDOWN_MAX = 60.0   # sanity cap so a malformed huge retry_after can't wedge Discord off for long


def _authHeaders() -> dict:
    return {"Authorization": f"Bot {config.DISCORD_BOT_TOKEN}", "Content-Type": "application/json"}


def _ownerMentions() -> dict:
    """allowed_mentions that can never expand past the configured owner."""
    oid = (config.DISCORD_HUMAN_USER_ID or "").strip()
    return {"parse": [], "users": [int(oid)] if oid.isdigit() else []}


def _request(method: str, path: str, *, json: Optional[dict] = None,
             params: Optional[dict] = None, retries: int = config.DISCORD_RETRY_MAX):
    """Single REST chokepoint. 429 -> sleep(retry_after) up to `retries` (milestone sends);
    pass retries=0 on the control-poll path so it never blocks the run loop. A hard 401 latches
    the whole surface off; 403/404 are logged but NEVER disable (a deleted message is normal)."""
    global _DISABLED, _RATE_LIMITED_UNTIL
    if _DISABLED or not config.DISCORD_BOT_TOKEN or not config.DISCORD_CHANNEL_ID:
        return None
    # Global 429 circuit breaker: while inside the rate-limit window, do not touch the network at all.
    if time.monotonic() < _RATE_LIMITED_UNTIL:
        return None
    url = f"{_API}{path}"
    attempt = 0
    while True:
        try:
            r = _SESSION.request(method, url, headers=_authHeaders(), json=json, params=params,
                                 timeout=config.DISCORD_REST_TIMEOUT)
        except Exception as e:  # noqa: BLE001
            LOG.warning("Discord %s %s failed: %s", method, path, e)
            return None
        if r.status_code == 429:
            try:
                retry_after = float((r.json() or {}).get("retry_after",
                                    r.headers.get("Retry-After", 1)))
            except Exception:  # noqa: BLE001
                retry_after = 1.0
            retry_after = min(max(retry_after, 0.0), _RL_COOLDOWN_MAX)
            # Arm the global breaker so the NEXT call (any path, any thread) short-circuits instead of
            # re-hitting the rate-limited API -- this is what stops the 429 storm even on retries=0.
            _RATE_LIMITED_UNTIL = time.monotonic() + retry_after
            if attempt < retries:
                time.sleep(retry_after)
                attempt += 1
                continue
            # poll path (retries=0): return now without blocking the run loop; the breaker above
            # throttles every subsequent call until the window passes. Log once (not per-spin).
            LOG.warning("Discord %s %s -> 429; global backoff %.1fs", method, path, retry_after)
            return r
        if r.status_code == 401:
            _DISABLED = True
            LOG.error("Discord auth failed (401) -> disabling Discord for this process")
        elif not (200 <= r.status_code < 300) and r.status_code != 404:
            LOG.warning("Discord %s %s -> %s: %s", method, path, r.status_code, (r.text or "")[:200])
        return r


def truncate(text, n: int) -> str:
    """Clamp to n chars, marking a clip with a trailing ellipsis."""
    text = str(text if text is not None else "")
    if n <= 1:
        return text[:max(n, 0)]
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _embedLen(embed: dict) -> int:
    total = len(str(embed.get("title", ""))) + len(str(embed.get("description", "")))
    total += len(str((embed.get("footer") or {}).get("text", "")))
    for f in embed.get("fields", []) or []:
        total += len(str(f.get("name", ""))) + len(str(f.get("value", "")))
    return total


def _clampEmbed(embed: dict) -> dict:
    """Guarantee a sendable embed: per-field clamp (no oversize field can 400 the whole message),
    <=25 fields, and a 6000-total budget enforced by shrinking the LARGEST field value first so the
    dashboard's dynamic tail rows are never silently dropped."""
    if not isinstance(embed, dict):
        return embed
    e = dict(embed)
    if isinstance(e.get("description"), str):
        e["description"] = truncate(e["description"], config.DISCORD_MAX_EMBED_DESC)
    fields = e.get("fields")
    if isinstance(fields, list):
        clamped = []
        for f in fields[:25]:
            if not isinstance(f, dict):
                continue
            nf = dict(f)
            nf["name"] = truncate(nf.get("name", ""), config.DISCORD_MAX_FIELD_NAME)
            nf["value"] = truncate(nf.get("value", ""), config.DISCORD_MAX_FIELD_VALUE) or "—"
            clamped.append(nf)
        e["fields"] = clamped
        guard = 0
        while _embedLen(e) > config.DISCORD_EMBED_TOTAL_MAX and guard < 50:
            guard += 1
            over = _embedLen(e) - config.DISCORD_EMBED_TOTAL_MAX
            biggest = max(e["fields"], key=lambda f: len(str(f.get("value", ""))), default=None)
            if biggest is None or len(str(biggest.get("value", ""))) <= 8:
                break
            cur_len = len(str(biggest["value"]))
            biggest["value"] = truncate(biggest["value"], max(8, cur_len - over - 1))
    return e


def createMessage(embed: dict, content: Optional[str] = None, components: Optional[list] = None) -> Optional[str]:
    payload: dict = {"embeds": [_clampEmbed(embed)]}
    if content:
        payload["content"] = content
        payload["allowed_mentions"] = _ownerMentions()
    if components is not None:
        payload["components"] = components
    r = _request("POST", f"/channels/{config.DISCORD_CHANNEL_ID}/messages", json=payload)
    if r is not None and 200 <= r.status_code < 300:
        try:
            return str(r.json().get("id"))
        except Exception:  # noqa: BLE001
            return None
    return None


def editMessageResult(message_id: str, embed: dict, content: Optional[str] = None,
                      components: Optional[list] = None) -> str:
    """Edit a message, returning a status the caller can ACT on:
      'ok'         -- edited (2xx)
      'not_found'  -- the message is genuinely gone (404) -> safe to recreate
      'transient'  -- None (429 breaker armed / timeout / network) or 429/5xx -> DO NOT recreate;
                      the message almost certainly still exists, just retry the edit next tick.
    Distinguishing these stops a transient Discord blip from spawning a DUPLICATE dashboard embed
    and burning the one-shot recreation guard."""
    if not message_id:
        return "not_found"
    payload: dict = {"embeds": [_clampEmbed(embed)]}
    if content is not None:
        payload["content"] = content
        if content:
            payload["allowed_mentions"] = _ownerMentions()
    if components is not None:
        payload["components"] = components
    r = _request("PATCH", f"/channels/{config.DISCORD_CHANNEL_ID}/messages/{message_id}", json=payload)
    if r is None:
        return "transient"
    if 200 <= r.status_code < 300:
        return "ok"
    if r.status_code == 404:
        return "not_found"
    return "transient"   # 429/5xx/etc -> retry, never recreate


def editMessage(message_id: str, embed: dict, content: Optional[str] = None,
                components: Optional[list] = None) -> bool:
    return editMessageResult(message_id, embed, content, components) == "ok"


def pinMessage(message_id: Optional[str]) -> bool:
    if not message_id:
        return False
    r = _request("PUT", f"/channels/{config.DISCORD_CHANNEL_ID}/pins/{message_id}")
    if r is None:
        return False
    if r.status_code == 400 and "pin" in (r.text or "").lower():
        LOG.error("Discord pin cap likely reached; old dashboards not unpinned")
    return 200 <= r.status_code < 300


def unpinMessage(message_id: Optional[str]) -> bool:
    """Idempotent: 404 (already unpinned / message gone) counts as success."""
    if not message_id:
        return False
    r = _request("DELETE", f"/channels/{config.DISCORD_CHANNEL_ID}/pins/{message_id}")
    if r is None:
        return False
    return (200 <= r.status_code < 300) or r.status_code == 404


def fetchMessagesAfter(after_id: Optional[str], limit: int = 25) -> tuple[list[dict], Optional[str]]:
    """Control-poll path: retries=0 so a 429 returns immediately and never blocks the run loop.
    Surfaces author_id so the poller can authorize. Single page (no burst paging)."""
    params: dict = {"limit": limit}
    if after_id:
        params["after"] = after_id
    r = _request("GET", f"/channels/{config.DISCORD_CHANNEL_ID}/messages", params=params, retries=0)
    if r is None or not (200 <= r.status_code < 300):
        return [], after_id
    try:
        msgs = r.json()
    except Exception:  # noqa: BLE001
        return [], after_id
    out = [{"id": str(m.get("id")), "content": m.get("content") or "",
            "author_is_bot": bool((m.get("author") or {}).get("bot")),
            "author_id": str((m.get("author") or {}).get("id") or "")} for m in reversed(msgs)]
    latest = out[-1]["id"] if out else after_id
    return out, latest


def baselineLatestId() -> Optional[str]:
    """Newest message id (no messages returned) -- used to SEED the control cursor at run start
    so a stale '!abort' from a prior run is never replayed. Best-effort/non-fatal."""
    r = _request("GET", f"/channels/{config.DISCORD_CHANNEL_ID}/messages",
                 params={"limit": 1}, retries=0)
    if r is None or not (200 <= r.status_code < 300):
        return None
    try:
        msgs = r.json()
        return str(msgs[0]["id"]) if msgs else None
    except Exception:  # noqa: BLE001
        return None


def sendEmbed(embed: dict, content: Optional[str] = None, components: Optional[list] = None,
              milestone: bool = False) -> dict:
    """Post a new embed message.  When ``milestone=True`` the embed is a non-critical run
    milestone (architect done, planning start, adversary heartbeat, self-ref notice) that is
    suppressed in night mode to keep the channel quiet during unattended overnight runs."""
    if milestone and config.NIGHT_MODE:
        return {"ok": True, "status": None, "suppressed": True}
    payload: dict = {"embeds": [_clampEmbed(embed)]}
    if content:
        payload["content"] = content
        payload["allowed_mentions"] = _ownerMentions()
    if components:
        payload["components"] = components
    r = _request("POST", f"/channels/{config.DISCORD_CHANNEL_ID}/messages", json=payload)
    return {"ok": r is not None and 200 <= r.status_code < 300,
            "status": getattr(r, "status_code", None)}


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
    v = (verdict or "").lower().strip()
    if verdict is None:
        color = statusColor("adversary")
    elif v in _CHALLENGED:
        color = statusColor("blocked")
    elif v in _APPROVED:
        color = statusColor("done")
    else:
        color = 0x95A5A6  # UNKNOWN -> neutral grey, never false-green
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


def noticeEmbed(reason: str, title: str = "ℹ️ 9TO5 — notice") -> dict:
    """An AUTONOMOUS, informational event the system already handled itself (a fallback was taken, a
    pause auto-resumed, the horizon was reached, a transient failure recovered, the run aborted/crashed
    and the supervisor will recover). 9to5 runs hands-off, so this INFORMS without ever claiming a
    'human decision is required' and without @-pinging anyone."""
    return {
        "title": title[:240],
        "color": statusColor("running"),
        "description": f"{reason[:4000]}",
        "timestamp": _nowIso(),
    }


def blockedEmbed(reason: str, question: Optional[str] = None) -> dict:
    desc = f"**{reason[:1500]}**"
    if question:
        q_lines = question[:1500].splitlines() or [""]
        quoted = "\n".join(f"> {line}" for line in q_lines)
        desc += f"\n\n━━━ Claude Code asks ━━━\n{quoted}"
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
    countable = done + failed
    sr_val = f"{round(100 * done / countable)}%" if countable else "—"
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
            {"name": "Success rate", "value": sr_val, "inline": True},
            {"name": "Time elapsed", "value": elapsed or "—", "inline": True},
            {"name": "Replans", "value": str(replans), "inline": True},
            {"name": "Adversary", "value": str(advs), "inline": True},
            {"name": "Progress", "value": subtaskTracker(state.subtasks), "inline": False},
            {"name": "Pull request", "value": pr_val, "inline": False},
        ],
        "footer": {"text": f"task {state.task_id[:8]}"},
    }


def sendBlocked(reason: str, question: Optional[str] = None) -> dict:
    """Severe: new message, owner ping only (allowed_mentions can't expand past owner), with
    Answer/Skip/Abort buttons."""
    return sendEmbed(blockedEmbed(reason, question), content=humanPing(), components=blockedComponents())


def gateNeededEmbed(gate: str) -> dict:
    return {
        "title": f"⏳ Approval needed — {gate}",
        "color": statusColor("paused"),
        "description": "Reply `!approve` / `!reject`, or use the web dashboard.",
        "timestamp": _nowIso(),
        "fields": [{"name": "Gate", "value": f"`{gate}`", "inline": True}],
    }


def subtaskFailedEmbed(subtask_id: str, title: str, verify_result: Optional[dict], attempts: int) -> dict:
    vr = verify_result or {}
    fields = [
        {"name": "Subtask", "value": truncate(f"`{subtask_id}` {title}", 256), "inline": False},
        {"name": "Attempts", "value": str(attempts), "inline": True},
        {"name": "Exit code", "value": str(vr.get("returncode", "—")), "inline": True},
        {"name": "Verify cmd", "value": f"`{truncate(str(vr.get('cmd') or 'exit'), 200)}`", "inline": False},
    ]
    stdout = (vr.get("stdout") or "").strip()
    stderr = (vr.get("stderr") or "").strip()
    output = (stdout or stderr)[:800]
    if output:
        fields.append({"name": "Output", "value": f"```\n{output}\n```", "inline": False})
    return {
        "title": "⚠️ Subtask failed verification",
        "color": statusColor("failed"),
        "timestamp": _nowIso(),
        "fields": fields,
        "footer": {"text": "task continues with remaining subtasks"},
    }


def abortedEmbed(reason: str, elapsed: str) -> dict:
    return {
        "title": "🛑 Run aborted",
        "color": statusColor("aborted"),
        "timestamp": _nowIso(),
        "fields": [
            {"name": "Reason", "value": truncate(reason, 512), "inline": False},
            {"name": "Elapsed", "value": elapsed or "—", "inline": True},
        ],
    }


def selfRefEmbed(branch: str, protected: tuple) -> dict:
    return {
        "title": "🧬 Self-referential run (9to5 editing 9to5)",
        "color": statusColor("replanning"),
        "timestamp": _nowIso(),
        "fields": [
            {"name": "Isolation branch", "value": f"`{branch}`", "inline": True},
            {"name": "Protected core files", "value": truncate(", ".join(protected), 1024), "inline": False},
        ],
    }
