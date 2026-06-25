"""ANSI mission-console HUD (T8 cinematic). A PURE renderer that turns live TaskState into
a sci-fi terminal frame inside a ```ansi fenced block -- green reticle, amber/red status,
a progress bar that visibly scans under load. Returns a content string ready to post (or
PATCH-edit in place like the dashboard); never raises.

Discord ANSI codeblocks support only SGR 30-37 (fg), 40-47 (bg), 1 (bold), 4 (underline) --
no 256-color/RGB -- so the palette is the 8 base colors. Clients that don't render ansi show
it as plain monospace text (an accepted, documented degrade).
"""
from __future__ import annotations

from typing import Optional

import config
from notifications import cv2

ESC = "\x1b"


def _c(code: str) -> str:
    return f"{ESC}[{code}m"


RESET = _c("0")
BOLD = _c("1")
FRAME = _c("36")   # cyan frame

# status -> ANSI fg code
_STATUS = {
    "executing": "32", "running": "32", "verifying": "32", "done": "32", "complete": "32",
    "architecting": "36", "planning": "36", "starting": "36", "resuming": "36",
    "adversary": "33", "paused": "33",
    "replanning": "35",
    "blocked": "31", "failed": "31", "aborted": "31",
}


def render(state, phase: str, *, events: Optional[list] = None, width: int = 36) -> str:
    """Return the full ```ansi HUD block for ``state``. Best-effort: any failure yields a
    minimal 'console offline' block rather than raising."""
    try:
        m = dict(state.meta)
        subs = [s for s in state.subtasks if s.get("status") != "removed"]
        done = sum(1 for s in subs if s.get("status") == "done")
        total = max(len(subs), 1)
        pct = done / total
        status = str(m.get("status", "?"))
        color = _c(_STATUS.get(status, "37"))

        cur = next((s for s in subs if s.get("status") == "in_progress"), None) \
            or next((s for s in subs if s.get("status") == "pending"), None)
        cur_txt = f"{cur['subtask_id']} {cur['title']}" if cur else "—"

        last_v = None
        for s in subs:
            if s.get("verify_result"):
                last_v = (s["subtask_id"], s["verify_result"])
        verify = (("OK " if last_v[1].get("passed") else "FAIL ") + last_v[0]) if last_v else "—"

        filled = max(0, min(width, round(width * pct)))
        bar = "█" * filled + "░" * (width - filled)
        el = cv2.elapsedStr(m.get("started_at"))
        eta = cv2.etaStr(m.get("started_at"), done, total)

        b = f"{FRAME}│{RESET}"
        lines = [
            f"{BOLD}{FRAME}┌─ NIGHTCLAW · MISSION CONSOLE ─────────────────┐{RESET}",
            f"{b} PHASE   {color}{BOLD}{phase.upper()}{RESET}",
            f"{b} STATUS  {color}{status}{RESET}",
            f"{b} [{color}{bar}{RESET}] {int(pct * 100):>3}%  {done}/{total}",
            f"{b} CURRENT {cur_txt[:40]}",
            f"{b} VERIFY  {verify[:40]}",
            f"{b} ELAPSED {el}   ETA {eta}",
            f"{BOLD}{FRAME}└───────────────────────────────────────────────┘{RESET}",
        ]
        return "```ansi\n" + "\n".join(lines) + "\n```"
    except Exception:  # noqa: BLE001 -- HUD is best-effort
        return "```ansi\n" + _c("31") + "NIGHTCLAW · console offline" + RESET + "\n```"
