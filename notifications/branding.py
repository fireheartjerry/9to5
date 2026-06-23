"""9TO5 Discord design system + rich embed builders. Pure (no network, no discord.py).
Central brand identity, the polished /command surfaces, and the control-panel component
row. Builds plain dicts; the transport layer (discord_bot._clampEmbed) guarantees limits."""
from __future__ import annotations

from typing import Optional

import config
from notifications import commands
from notifications import discord_bot as discord

BRAND = config.BRAND_COLOR

# ---- control-panel components (raw dicts for REST; custom_ids shared with views.py) ----
CONTROL_PANEL_IDS = {
    "pause": "cp_pause", "resume": "cp_resume", "abort": "cp_abort",
    "approve": "cp_approve", "reject": "cp_reject", "skip": "cp_skip",
}


def controlPanelRow() -> list:
    """Two action rows of control buttons (<=5/row). Handled by views.ControlPanelView."""
    return [
        {"type": 1, "components": [
            {"type": 2, "style": 1, "label": "Pause", "custom_id": "cp_pause", "emoji": {"name": "⏸️"}},
            {"type": 2, "style": 3, "label": "Resume", "custom_id": "cp_resume", "emoji": {"name": "▶️"}},
            {"type": 2, "style": 4, "label": "Abort", "custom_id": "cp_abort", "emoji": {"name": "🛑"}},
        ]},
        {"type": 1, "components": [
            {"type": 2, "style": 3, "label": "Approve", "custom_id": "cp_approve", "emoji": {"name": "✅"}},
            {"type": 2, "style": 2, "label": "Reject", "custom_id": "cp_reject", "emoji": {"name": "⚔️"}},
            {"type": 2, "style": 2, "label": "Skip", "custom_id": "cp_skip", "emoji": {"name": "⏭️"}},
        ]},
    ]


def brandEmbed(title: str, *, description: Optional[str] = None, color: Optional[int] = None,
               fields: Optional[list] = None, uptime: Optional[str] = None) -> dict:
    e: dict = {
        "title": title,
        "color": color if color is not None else BRAND,
        "timestamp": discord._nowIso(),
        "author": {"name": f"9TO5 v{config.VERSION}"},
        "footer": {"text": f"9TO5 v{config.VERSION}" + (f" · up {uptime}" if uptime else "")},
    }
    if config.BRAND_ICON_URL:
        e["author"]["icon_url"] = config.BRAND_ICON_URL
    if description is not None:
        e["description"] = description
    if fields:
        e["fields"] = fields
    return e


_CATEGORIES = {
    "Control": ["abort", "pause", "approve", "reject", "skip", "add", "retry"],
    "Info": ["status", "plan", "log", "help"],
    "Run": ["work", "runs", "run", "resume"],   # /resume is unified: unpause, or resume a prior run by id
}
_EXTRA_HELP = {
    "work": "launch a new run (blank = guided setup)",
    "runs": "list recent runs", "run": "inspect a run by id", "resume": "resume a run by id",
    "ping": "latency, uptime, version", "diagnostics": "environment health checks",
    "metrics": "aggregate run metrics", "audit": "recent control actions",
}


def _help(name: str) -> str:
    if name in commands.COMMAND_REGISTRY:
        return commands.COMMAND_REGISTRY[name]["help"]
    return _EXTRA_HELP.get(name, "")


def helpEmbed() -> dict:
    fields = []
    for cat, names in _CATEGORIES.items():
        fields.append({"name": cat, "value": "\n".join(f"`/{n}` — {_help(n)}" for n in names),
                       "inline": False})
    fields.append({"name": "Observability",
                   "value": "\n".join(f"`/{n}` — {_EXTRA_HELP[n]}"
                                      for n in ("ping", "diagnostics", "metrics", "audit")),
                   "inline": False})
    return brandEmbed("📖 9TO5 — commands",
                      description="Slash-first. `!`-prefixed text commands also work.",
                      fields=fields)


def statusEmbed(state, bus, uptime: Optional[str] = None) -> dict:
    m = state.meta
    done, total = state.progress()
    cur = next((s for s in state.subtasks if s["status"] == "in_progress"), None) or state.nextActionable()
    cur_txt = f"`{cur['subtask_id']}` {cur['title']}" if cur else "—"
    gate = bus.getPendingGate() if bus else None
    fields = [
        {"name": "Status", "value": f"`{m.get('status', '?')}`", "inline": True},
        {"name": "Mode", "value": f"`{m.get('control_mode', 'watch')}`", "inline": True},
        {"name": "Progress", "value": f"{done}/{total}", "inline": True},
        {"name": "Current", "value": discord.truncate(cur_txt, 1024), "inline": False},
        {"name": "Working dir", "value": f"`{discord.truncate(m.get('work_dir') or '—', 200)}`", "inline": False},
    ]
    if gate:
        fields.append({"name": "⏳ Gate", "value": f"`{gate}` — /approve or /reject", "inline": False})
    return brandEmbed("📊 Run status",
                      description=f"**{discord.truncate(m.get('goal_raw', ''), 300)}**\n"
                                  f"{discord.progressBar(done, total)}\n"
                                  f"{discord.subtaskTracker(state.subtasks)}",
                      color=discord.statusColor(m.get("status")), fields=fields, uptime=uptime)


_PLAN_ICON = {"done": "✅", "in_progress": "⚡", "failed": "❌", "pending": "⬜"}


def _planLines(subtasks) -> list[str]:
    return [f"{_PLAN_ICON.get(s['status'], '⬜')} `{s['subtask_id']}` {s['title']}"
            for s in subtasks if s["status"] != "removed"]


def planEmbed(state, page: int = 0, per: int = 10):
    lines = _planLines(state.subtasks)
    total_pages = max(1, (len(lines) + per - 1) // per)
    page = max(0, min(page, total_pages - 1))
    chunk = lines[page * per:(page + 1) * per] or ["(no subtasks)"]
    e = brandEmbed(f"🗺️ Plan ({page + 1}/{total_pages})", description="\n".join(chunk),
                   color=discord.statusColor(state.meta.get("status")))
    return e, total_pages


def runsEmbed(summaries, page: int = 0, per: int = 8):
    total_pages = max(1, (len(summaries) + per - 1) // per)
    page = max(0, min(page, total_pages - 1))
    chunk = summaries[page * per:(page + 1) * per]
    lines = [f"`{s['task_id'][:8]}` [{s['status']}] {s['done']}/{s['total']} — "
             f"{discord.truncate(s['goal'], 60)}" for s in chunk] or ["(no runs yet)"]
    e = brandEmbed(f"🗂️ Recent runs ({page + 1}/{total_pages})", description="\n".join(lines))
    return e, total_pages


def runEmbed(state) -> dict:
    m = state.meta
    done, total = state.progress()
    fields = [
        {"name": "Task", "value": f"`{state.task_id[:8]}`", "inline": True},
        {"name": "Status", "value": f"`{m.get('status', '?')}`", "inline": True},
        {"name": "Progress", "value": f"{done}/{total}", "inline": True},
        {"name": "Started", "value": discord.relTime(m.get("started_at")), "inline": True},
        {"name": "Mode", "value": f"`{m.get('control_mode', 'watch')}`", "inline": True},
        {"name": "Working dir", "value": f"`{discord.truncate(m.get('work_dir') or '—', 200)}`", "inline": False},
    ]
    return brandEmbed("🔎 Run detail",
                      description=f"**{discord.truncate(m.get('goal_raw', ''), 400)}**\n"
                                  f"{discord.progressBar(done, total)}",
                      color=discord.statusColor(m.get("status")), fields=fields)


def diagnosticsEmbed(checks) -> dict:
    lines = []
    for c in checks:
        mark = "🟢" if c["ok"] else "🔴"
        line = f"{mark} **{c['name']}** — {discord.truncate(c['detail'], 120)}"
        if not c["ok"] and c.get("fix"):
            line += f"\n  ↳ _{discord.truncate(c['fix'], 120)}_"
        lines.append(line)
    n_ok = sum(1 for c in checks if c["ok"])
    color = discord.statusColor("done") if n_ok == len(checks) else discord.statusColor("blocked")
    return brandEmbed(f"🩺 Diagnostics — {n_ok}/{len(checks)} healthy",
                      description="\n".join(lines) or "—", color=color)


def metricsEmbed(m) -> dict:
    sr, avg = m["success_rate"], m["avg_duration_seconds"]
    fields = [
        {"name": "Total runs", "value": str(m["total_runs"]), "inline": True},
        {"name": "Success rate", "value": (f"{round(sr * 100)}%" if sr is not None else "—"), "inline": True},
        {"name": "Avg duration",
         "value": (f"{int(avg // 60)}m{int(avg % 60):02d}s" if avg is not None else "—"), "inline": True},
        {"name": "Subtasks passed", "value": f"{m['subtasks_passed']}/{m['subtasks_total']}", "inline": True},
        {"name": "By status",
         "value": (", ".join(f"{k}:{v}" for k, v in sorted(m["by_status"].items())) or "—"), "inline": False},
    ]
    return brandEmbed("📈 Run metrics", fields=fields)


def pingEmbed(latency_ms, uptime, version) -> dict:
    return brandEmbed("🏓 Pong", uptime=uptime, fields=[
        {"name": "Gateway latency", "value": f"{latency_ms} ms", "inline": True},
        {"name": "Uptime", "value": uptime, "inline": True},
        {"name": "Version", "value": f"v{version}", "inline": True},
    ])


def auditEmbed(entries) -> dict:
    if not entries:
        return brandEmbed("📋 Audit log", description="_no actions recorded yet_")
    lines = []
    for e in entries[-15:]:
        tid = f" · {e['task_id'][:8]}" if e.get("task_id") else ""
        lines.append(f"`{(e.get('at') or '')[:19]}` <@{e.get('user_id', '?')}> "
                     f"**{e.get('action', '?')}**{tid}")
    return brandEmbed("📋 Audit log", description="\n".join(lines))
