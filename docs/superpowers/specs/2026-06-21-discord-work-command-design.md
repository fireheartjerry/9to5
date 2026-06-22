# Discord `/work` Launch Command — Design

> **Status:** approved design (brainstorming output). Next step: implementation plan
> (`docs/superpowers/plans/`). This spec is the contract; the plan sequences the work.

## Objective

Let the human start a full 9TO5 run **from Discord** exactly as they would from the
CLI (`main.py --goal "…" --hours N …`), via a `/work` slash command with optional
parameters. When invoked with no parameters, the bot runs a Discord-native
interactive onboarding (modal + dropdowns) to collect the details and then launches.
Additionally, the pinned live dashboard message is **unpinned automatically when the
run ends**, so the channel doesn't accumulate stale pins.

## Background (current state)

- `notifications/command_bot.py` is the always-on Discord process
  (`python -m notifications.command_bot`). It uses `!`-prefix text commands
  (`on_message`) + component buttons, and only **controls the latest task** via its
  `ControlBus`. It **cannot start a run today.**
- A run is started only by `main.py` (CLI): it creates the `TaskState`, runs Ollama
  elaboration + universe extraction, optionally asks the human to approve the
  elaboration (skipped by `--auto-approve`), then calls `Orchestrator().runFull(...)`,
  which **blocks**, starts the web dashboard + Discord dashboard, and polls the
  channel for `!` control commands.
- `notifications/dashboard.py` (`DiscordDashboard`) creates **one** embed at run start
  and **pins** it (`discord.pinMessage`). **Nothing ever unpins it**, and there is no
  `unpinMessage` REST helper.
- Stack: `discord.py >= 2.3` (supports `app_commands` slash commands, modals, views),
  Python 3.11, `requests` for Discord REST. Tests live in `tests/test_*.py`.

## Decisions (locked)

| Question | Decision |
|----------|----------|
| Onboarding richness (no params) | **Modal + dropdowns** — modal collects free text, then a view with dropdowns + Launch button collects the enum options |
| Who may launch | **Restrict to `DISCORD_HUMAN_USER_ID`** (if set); others get a polite ephemeral refusal |
| If a run is already active | **Block** — refuse, tell the user to abort the active run first |
| What to unpin on finish | **This run's dashboard message**, on any terminal state |
| Launch mechanism | **Subprocess spawn of `main.py`** (detached child), reusing all existing run machinery |

## Approaches considered

- **A — Subprocess spawn of `main.py` (chosen).** `/work` builds an argv list and
  spawns `venv\Scripts\python main.py --goal … --auto-approve …` as a detached child
  (`Popen` + `CREATE_NEW_PROCESS_GROUP`, matching `executor.py`'s Windows handling).
  Reuses elaboration, universe extraction, both dashboards, control polling, terminal
  control verbatim. Bot stays responsive (heavy Ollama + blocking `runFull` live in
  the child). A bot restart does not kill the run. Passing the goal as an argv list
  avoids all shell quoting/newline issues.
- **B — In-process background thread.** Run `runFull` in a thread inside the bot.
  Rejected: a bot restart kills the run; must re-implement main's elaboration/universe/
  web-dashboard setup; asyncio-loop ↔ blocking-call handoff is fragile.
- **C — Refactor `main.py` into a shared launcher.** Rejected as unnecessary: `main.py`
  already *is* the launcher; the only reusable/testable piece worth extracting is the
  argv-builder, which Approach A provides in `work_launcher.py`.

## Architecture

A thin discord-specific UI layer (`command_bot.py`) sits on top of a **pure, testable
launcher core** (`work_launcher.py`, no discord import). The launcher validates input
and spawns `main.py`; everything downstream (elaboration → universe → `runFull`) is the
existing pipeline, unchanged except for the new unpin-on-finish behavior.

```
/work [params]
  → permission gate (caller == DISCORD_HUMAN_USER_ID?)
  → concurrency gate (work_launcher.activeRun() is None?)
  ├─ goal present → validate → spawn(main.py child) → ✅ ephemeral confirmation
  └─ goal absent  → WorkModal (goal, hours, work_dir)
                     → WorkSetupView (dropdowns: mode/parallel/PR + Launch/Cancel)
                     → validate → spawn → ✅ confirmation
        ↓
  main.py child: TaskState.create → elaborate → universe → runFull
        ↓ runFull pins the dashboard at start, runs to a terminal state
  runFull `finally:` → dashboard.unpin()   ← satisfies "unpin when work is done"
```

## Components

### New — `notifications/work_launcher.py` (pure; **no** discord import)

The testable core. Exposes:

- `WorkRequest` dataclass: `goal: str`, `hours: float = 1.0`, `mode: str = "watch"`,
  `parallel: int = 1`, `work_dir: str | None = None`, `no_pr: bool = False`.
- `parseHours(raw: str | float | None) -> float` — tolerant parse (`"2"`, `"2h"`,
  `"1.5"`); invalid/empty → default `1.0`; clamp to `[HOURS_MIN, HOURS_MAX] = [0.1, 24]`.
- `validate(req: WorkRequest) -> list[str]` — returns human-readable errors:
  goal non-empty after strip; `0.1 ≤ hours ≤ 24`; `mode ∈ {"watch","gated"}`;
  `parallel ≥ 1`; `work_dir` (if given) must exist as a directory.
- `buildArgv(req: WorkRequest) -> list[str]` — returns
  `[str(config.VENV_PYTHON), str(config.PROJECT_ROOT / "main.py"), "--goal", req.goal,
  "--hours", str(req.hours), "--auto-approve", "--mode", req.mode,
  "--parallel", str(req.parallel)]` plus `["--no-pr"]` if `req.no_pr` and
  `["--work-dir", req.work_dir]` if set. Always includes `--auto-approve`.
- `activeRun() -> TaskState | None` — `TaskState.loadLatest()` if its `meta.status`
  is **not** terminal, else `None`. Reuse `TaskState._TERMINAL`
  (`done, complete, aborted, partial, blocked, failed`) as the source of truth rather
  than redefining the set here, so the two never drift. Powers the Block check.
- `spawn(req: WorkRequest) -> int` — the only side-effectful function. Opens a per-run
  logfile under `config.LOG_PATH` (`work-<UTC-stamp>.log`), then
  `subprocess.Popen(buildArgv(req), cwd=str(config.PROJECT_ROOT), stdin=DEVNULL,
  stdout=logfile, stderr=STDOUT, creationflags=CREATE_NEW_PROCESS_GROUP)`. Returns the
  child PID. Kept thin so tests patch `subprocess.Popen`.

`HOURS_MIN` and `HOURS_MAX` are module constants (`ALL_CAPS`); the terminal-status set
is reused from `TaskState._TERMINAL`. The launcher imports only `config`, `state.task`,
stdlib.

### Modify — `notifications/discord_bot.py`

Add `unpinMessage(message_id: str | None) -> bool` — REST `DELETE`
`/channels/{channel}/pins/{message_id}`, mirroring `pinMessage`'s guards and return
shape. Best-effort: returns `False` (logged) on any failure or missing config.

### Modify — `notifications/dashboard.py`

Add `DiscordDashboard.unpin() -> None` — if `DISCORD_DASHBOARD` and `self.message_id`,
call `discord.unpinMessage(self.message_id)` and log; otherwise no-op. Idempotent and
exception-safe (never raises).

### Modify — `orchestrator.py`

In `runFull`'s `finally:` block, alongside `stopWebDashboard()`, add a best-effort
`dashboard.unpin()` (wrapped in try/except). `dashboard` is already in scope (created
before the `try`). This unpins on **every** terminal exit: complete, aborted, blocked,
crashed. No other call site changes.

### Modify — `config.py`

Add optional `DISCORD_GUILD_ID: int` (parsed like `DISCORD_CHANNEL_ID`, default `0`).
When non-zero, slash commands register to that guild (instant); when `0`, they register
globally (can take up to ~1h to propagate). No other config changes required
(`VENV_PYTHON`, `PROJECT_ROOT`, `LOG_PATH`, `DISCORD_HUMAN_USER_ID` already exist).

### Modify — `notifications/command_bot.py` (thin discord UI layer)

Keep **all** existing `!` commands and the button handler intact. Add:

- An `app_commands.CommandTree(client)`; in `on_ready`, `await tree.sync(guild=…)`
  (guild if `DISCORD_GUILD_ID` else global). Log the synced command count.
- A small helper `_isAuthorized(user_id) -> bool` — `True` if `DISCORD_HUMAN_USER_ID`
  is unset, else `user_id == int(DISCORD_HUMAN_USER_ID)`.
- A helper `_launchOrError(req) -> str` (pure-ish, wraps launcher): run `validate`;
  if errors → return error text; if `activeRun()` → return "run active" text;
  else `spawn(req)` and return a confirmation string. Used by every launch path so
  gating is centralized. (Permission is checked at the interaction boundary.)
- `/work` slash command with optional params:
  `goal: str | None`, `hours: float | None`, `mode: choice[watch,gated] | None`,
  `parallel: int | None`, `no_pr: bool | None`, `work_dir: str | None`.
  1. Permission gate → ephemeral refusal if unauthorized.
  2. If `goal` provided → build `WorkRequest` (defaults via `parseHours`, etc.),
     `_launchOrError`, reply ephemerally (confirmation embed or error).
  3. If `goal` absent → `interaction.response.send_modal(WorkModal(...))`
     (prefilled with any params that *were* given).
- `WorkModal(discord.ui.Modal)` — text inputs only (Discord constraint):
  `goal` (paragraph, required), `hours` (short, default "1"), `work_dir` (short,
  optional). On submit → respond with an ephemeral message carrying a `WorkSetupView`
  seeded with the modal values.
- `WorkSetupView(discord.ui.View)` — dropdowns (`discord.ui.Select`) for **mode**
  (watch/gated), **parallel** (1/2/3), **PR** (create / skip), plus **Launch** and
  **Cancel** buttons. Holds the in-progress `WorkRequest` fields. Each component
  interaction re-checks it's the original user; `Launch` calls `_launchOrError` and
  edits the message to the result; 300s `timeout` disables the components.

### New — `tests/test_work_launcher.py`

Pure-logic unit tests (no discord import, no real subprocess):
- `parseHours`: `"2"→2.0`, `"2h"→2.0`, `"1.5"→1.5`, `""/None/"junk"→1.0`, clamp `"99"→24`, `"0"→0.1`.
- `validate`: empty goal flagged; bad mode flagged; `parallel=0` flagged; valid req → `[]`.
- `buildArgv`: contains `--auto-approve`, goal/hours/mode/parallel present; `--no-pr`
  only when set; `--work-dir` only when set; first two elements are venv python + main.py.
- `activeRun`: monkeypatch `TaskState.loadLatest` → non-terminal status returns the
  state; terminal status returns `None`; no task returns `None`.
- `spawn`: monkeypatch `subprocess.Popen` to a fake; assert it's called with the argv
  from `buildArgv`, `cwd=PROJECT_ROOT`, and a `CREATE_NEW_PROCESS_GROUP` creationflag;
  returns the fake PID.

## Data contracts

`WorkRequest` (the single object passed launcher↔UI):
```python
WorkRequest(goal="add retries to X", hours=2.0, mode="gated",
            parallel=1, work_dir=None, no_pr=False)
```
`buildArgv(WorkRequest(...))` →
```
[<venv python>, <PROJECT_ROOT>/main.py, --goal, "add retries to X",
 --hours, 2.0, --auto-approve, --mode, gated, --parallel, 1]
```

## Error handling

- **Invalid params** → ephemeral validation errors; no spawn.
- **Active run (Block)** → ephemeral "Run `<task_id8>` is `<status>`; abort it first
  (`!abort`)."; no spawn.
- **Unauthorized caller** → ephemeral refusal; no spawn.
- **Spawn failure** (`Popen` raises) → ephemeral error, logged; no crash.
- **Modal/view timeout** → buttons disabled; user can re-run `/work`.
- **Unpin failure** → logged, non-fatal (best-effort, exactly like pin).
- **Goal with quotes/newlines** → safe; argv list, no shell.

## Out of scope (YAGNI)

- `!work` text fallback (slash command is the requested surface).
- Multiple concurrent runs / a run queue (Block makes it single-run).
- Editing the elaboration from Discord (runs use `--auto-approve`; gate at plan via
  `--mode gated` instead).
- Unpinning unrelated/older pins (only this run's dashboard is unpinned).

## Operational requirements

- The bot's invite must include the `applications.commands` OAuth scope for slash
  commands to register.
- For instant slash availability during dev, set `DISCORD_GUILD_ID` in
  `C:\supercritical\.env`; otherwise global registration may take up to ~1h.
- `/work` always passes `--auto-approve`; use `--mode gated` (a `/work` option) to keep
  the plan/PR approval gates, answered with `!approve` / `!reject` or the web buttons.

## Verification (cadence for the plan)

The project is a git repo with a `tests/` harness. After each component:
`py_compile` + import. Core launcher logic: run `tests/test_work_launcher.py`.
Discord layer (gateway, hard to unit-test without a token): **import-smoke**
`python -c "import notifications.command_bot"` to prove it loads, builds the tree, and
defines the modal/view classes. Full end-to-end (`/work` in a live channel) is a manual
smoke documented in the plan.
