# `notifications/` -- surfaces (derived views), never a state machine

Discord + web dashboards, the command bot, cogs, embeds, metrics. Index: `notifications/AGENTS.md`.
Conceptual home of "Nightclaw" -- see `docs/NIGHTCLAW.md`.

## What lives here
- **Discord REST**: `discord/` holds the raw HTTP client, channel helpers, and embed builders. `discord_bot.py` remains the public facade.
- **Live surfaces**: `surfaces/` holds the Discord dashboard, web dashboard, Components V2 cockpit, terminal mirror, and console HUD.
- **Presentation**: `presentation/` holds Discord views, branding, icons, personas, visuals, and themes.
- **Runtime plumbing**: `runtime/` holds event streams, subprocess feeds, tunnels, run arcs, and work-launcher helpers.
- **Command surface**: `commands.py` (the `!`-command spine), `command_bot.py`, `slash.py`, and `bot/` (cogs/UI).

Top-level modules such as `notifications.dashboard`, `notifications.views_run`, and
`notifications.work_launcher` are compatibility aliases for the new packages. New code should
prefer the package path when it makes ownership clearer, while old imports keep working.

## The one rule
These are **windows into state, not competing state machines.** Display must derive from canonical
run state (`state/task.py`); control intent flows through the **ControlBus** (`platform_core/runtime/control.py`). Never
persist authoritative state in a dashboard path. Respect Discord embed/field limits (clamp).

## Tests
`tests/test_dashboard*.py`, `tests/test_webdash_control.py`, `tests/test_*notification*.py`, `tests/test_control_concurrency.py`, ...
