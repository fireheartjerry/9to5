# Nightclaw

Nightclaw is the Discord bot / orchestrator-facing bot surface inside 9TO5.

For now, any task mentioning Nightclaw should be interpreted as changing the actual 9TO5 bot/dashboard/control infrastructure, not some separate human-controlled agent.

## Terminology

Examples:

- "improve Nightclaw CI/CD" means improve the internal CI/CD or subprocess/repo workflow around the Nightclaw/9TO5 bot system.
- "fix Nightclaw dashboard" means modify Discord/web dashboard surfaces.
- "improve Nightclaw command handling" means modify command bot/cogs/control command wiring.
- "make Nightclaw more reliable" means improve 9TO5 bot reliability, state sync, error handling, dashboard consistency, or control behavior.

## Entrypoint

`nightclaw.py` (repo root) — thin entrypoint that calls `notifications/command_bot.runCommandBot()`.

```bash
python nightclaw.py    # start the gateway bot
```

## Likely files

```txt
nightclaw.py
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

## Live Terminal (paginated, cross-process)

A second pinned surface streams the raw terminal of every sub-process as a paginated
message with ◀ Prev · ⏸ Freeze · Raw · Next ▶ · 📷 Snapshot buttons.

- **Pages = lanes.** Every layer publishes one line per action to the `LiveEventBus` as a
  named lane via `notifications/lane_feed.py:laneTap(lane, line)`: `brain` (`llm_io.py`),
  `orchestrator` (`run_loop_mixin`/`run_phase_mixin`), `browser` (`agents/browser_executor.py`),
  `native` (`agents/native_executor.py`), and each subtask `st-NNN` (already via
  `SubprocessFeed`). `LiveEventBus.lanes()` returns them in first-activity order.
- **Rendering** is a pure function, `notifications/terminal_render.py:render(...)` — header
  (page x/N, lane, running/idle, elapsed) + one fenced block of the newest lines + footer;
  hard-capped ≤1900 chars; never raises.
- **Surface** (`notifications/terminal_surface.py:TerminalSurface`) runs in a **daemon
  thread inside the orchestrator process** (same place as the web dashboard). Its
  `EditThrottle` edits the pinned message only on content change, ≥1.2s floor, backing off
  on `transient` (429/5xx) and honoring Retry-After; a genuine 404 recreates once. Only the
  viewed page is ever edited — N sub-processes cost the same as one.
- **Cross-process buttons.** The buttons are handled by the *bot* process; the surface lives
  in the *orchestrator* process. They bridge through the filesystem
  (`notifications/terminal_ipc.py`): the view writes nav intent to `state/ipc/terminal_nav.json`
  (`bump_nav`), the surface reads it each tick and writes a mirror
  (`state/ipc/terminal_mirror.json`: body + page_count + lane ids) that the view reads for
  snapshots and page clamping. Nav latency ≈ one tick (~0.4s). `TerminalView` is a persistent
  view (`timeout=None`, `term_*` custom_ids) registered in `notifications/bot/core.py`, so it
  survives multi-hour runs and bot restarts. Deep browser/native telemetry still lives on the
  web dashboard (`/api/raw`).

## Commands

### Slash commands (Discord app_commands)

```txt
/work              Start a 9TO5 run
/wipe              Factory reset — granular wipe of state, vault, logs
/runs              List recent runs (paginated)
/run <id>          Inspect a run by id
/resume [id]       Resume paused run (or resume prior run by id)
/create-pr <id>    Manually create a PR for any completed run (bypasses test gate, posts to Discord)
/pause             Pause current run
/abort             Abort current run
/status            Show current run status
```

`/work` can target either a local `work_dir` or a managed clone via `repo_url`
and optional `repo_ref`. See `docs/EXTERNAL_PROJECTS.md`.

### `/create-pr` details

**Purpose:** Force-create a PR for a completed run, bypassing the test-suite gate. Useful when:
- Tests pass locally but the gate held the PR
- You want to override the degradation check
- You need to manually cherry-pick changes

**Usage:**
```
/create-pr task_id: 9a3853b4
/create-pr task_id: st_abc123def456
```

**Behavior:**
- Validates task is complete (status = `done` or `partial`)
- Creates PR on the branch
- Posts success embed to Discord (visible to all)
- Reports errors: merge conflicts, auth, no changes, etc.

**Permissions:** Owner only (via `DISCORD_HUMAN_USER_ID`).

Nightclaw-launched `/work` runs always attempt to create a PR at completion.
Red tests, degraded progress, or adversary concerns are reported as review
feedback instead of hiding the PR; only Git/GitHub failures or no tracked
changes can prevent the PR from being created.

Legacy `!` prefix commands still work (parsed by gateway bot).

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
