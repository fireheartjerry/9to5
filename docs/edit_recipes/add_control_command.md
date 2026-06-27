# Add Control Command

Use when adding Discord/web/gateway commands that affect runs.

## Read first

- `CLAUDE.md`
- `docs/NIGHTCLAW.md`
- `docs/STATE.md`
- `docs/DANGER_MAP.md`

## Likely files

- `platform_core/runtime/control.py`
- `notifications/commands.py`
- `notifications/command_bot.py`
- `notifications/webdash.py`
- `notifications/bot/cogs/*`
- control tests
- `docs/NIGHTCLAW.md`
- `docs/STATE.md`

## Rules

- ControlBus owns canonical command state.
- Discord/web are command surfaces, not state machines.
- Preserve owner/auth behavior.
- Make command idempotent where possible.

## Verification

Run ControlBus tests and command routing tests. Run integration fake-run for pause/resume/abort if behavior is lifecycle-affecting.
