# Nightclaw

Nightclaw is the Discord bot / orchestrator-facing bot surface inside 9TO5.

For now, any task mentioning Nightclaw should be interpreted as changing the actual 9TO5 bot/dashboard/control infrastructure, not some separate human-controlled agent.

## Terminology

Examples:

- "improve Nightclaw CI/CD" means improve the internal CI/CD or subprocess/repo workflow around the Nightclaw/9TO5 bot system.
- "fix Nightclaw dashboard" means modify Discord/web dashboard surfaces.
- "improve Nightclaw command handling" means modify command bot/cogs/control command wiring.
- "make Nightclaw more reliable" means improve 9TO5 bot reliability, state sync, error handling, dashboard consistency, or control behavior.

## Likely files

```txt
notifications/dashboard.py
notifications/discord_bot.py
notifications/webdash.py
notifications/command_bot.py
notifications/commands.py
notifications/branding.py
notifications/slash.py
notifications/views.py
notifications/audit.py
notifications/metrics.py
notifications/cv2.py
notifications/visuals.py
notifications/theme.py
notifications/console_hud.py
notifications/personas.py
notifications/cast.py
notifications/ask.py
notifications/engagement.py
notifications/ops.py

notifications/bot/
  core.py
  cogs/
  ui/
```

## Gateway architecture

The Discord gateway bot may use `discord.ext.commands.Bot` with hot-reloadable cogs.

The run may also poll the Discord channel through REST between steps so commands like `!abort` can work without the gateway bot running.

Preserve the split:

- REST polling for minimal control from `main.py`
- gateway bot for richer commands/UI
- ControlBus as the shared control state

## Source-of-truth rule

Nightclaw is a surface. It should not become the canonical state machine.

| Concern | Source |
|---|---|
| Run state | task state / canonical store |
| Pause/resume/abort/approval | ControlBus |
| Verification status | verifier results |
| Dashboard display | derived from state |
| Discord messages | display/control surface |

## Live dashboard

The live Discord dashboard should:

- create one embed at run start
- patch-edit that embed every step
- show status, subtask progress, attempts, last verification, elapsed/ETA, and recent events
- avoid exceeding Discord embed limits
- clamp verbose fields
- avoid treating display payload as canonical state

## Commands

Known commands may include:

```txt
!status
!plan
!log
!abort
!pause
!resume
!approve
!reject
!skip <id>
!add <title>
!retry
```

If command behavior changes, update:

- `docs/NIGHTCLAW.md`
- `docs/STATE.md` if ControlBus state changes
- `docs/TESTING.md` if test commands or verification strategy changes
- `LLM_MAP.md` if file ownership changes

## Frontier Discord lab

Branch context, if present:

```txt
feat/discord-frontier-lab
```

Feature surfaces may be flag-gated by `DISCORD_LAB_MODE` and per-feature flags.

Potential surfaces:

- Components-V2 mission-control cockpit
- Pillow hero visuals
- ANSI HUD
- Ask Nightclaw local Ollama Q&A
- Cast webhook personas
- Adversary duel-card
- native Poll gate approvals
- super-reaction approve
- silence watchdog
- in-Discord plan editor
- context menus
- time-travel

## Nightclaw edit checklist

Before editing:

1. Read `CLAUDE.md`.
2. Read this file.
3. Read `docs/STATE.md` if touching control/state.
4. Read `docs/DANGER_MAP.md` if touching command auth, control, or run state.
5. Identify whether change is display-only or state/control-affecting.

After editing:

1. Run focused dashboard/command tests.
2. Run fake-backend integration if control/state changed.
3. Update docs.
4. Report whether live Discord checks were skipped.
