# `notifications/` — surfaces (derived views), never a state machine

Discord + web dashboards, the command bot, cogs, embeds, metrics. Index: `notifications/AGENTS.md`.
Conceptual home of "Nightclaw" — see `docs/NIGHTCLAW.md`.

## What lives here
- **Live dashboard** — `dashboard.py` (one embed, PATCH-edited every step), `discord_bot.py` (milestone embeds + REST).
- **Web** — `webdash.py` (stdlib HTTP server + control buttons).
- **Command surface** — `commands.py` (the `!`-command spine), `command_bot.py`, `bot/` (cogs/UI).
- **Presentation** — `views.py`, `branding.py`, `cv2.py`, `visuals.py`, `theme.py`, `console_hud.py`, `metrics.py`.

## The one rule
These are **windows into state, not competing state machines.** Display must derive from canonical
run state (`state/task.py`); control intent flows through the **ControlBus** (`control.py`). Never
persist authoritative state in a dashboard path. Respect Discord embed/field limits (clamp).

## Tests
`tests/test_dashboard*.py`, `tests/test_webdash_control.py`, `tests/test_*notification*.py`, `tests/test_control_concurrency.py`, …
