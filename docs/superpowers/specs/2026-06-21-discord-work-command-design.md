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
  `C:\9to5\.env`; otherwise global registration may take up to ~1h.
- `/work` always passes `--auto-approve`; use `--mode gated` (a `/work` option) to keep
  the plan/PR approval gates, answered with `!approve` / `!reject` or the web buttons.

## Verification (cadence for the plan)

The project is a git repo with a `tests/` harness. After each component:
`py_compile` + import. Core launcher logic: run `tests/test_work_launcher.py`.
Discord layer (gateway, hard to unit-test without a token): **import-smoke**
`python -c "import notifications.command_bot"` to prove it loads, builds the tree, and
defines the modal/view classes. Full end-to-end (`/work` in a live channel) is a manual
smoke documented in the plan.

---

# Addendum v2 — full Discord-surface hardening + professionalization

Scope expanded (per user) from "`/work` + unpin" to **robustness, well-developedness,
and professionalism across the entire Discord integration**: `discord_bot.py`,
`dashboard.py`, `command_bot.py`, and the orchestrator's Discord usage. Produced by a
5-lens parallel audit (48 findings) → synthesis → adversarial critique. The critique's
corrections are **baked into the items below**: over-engineered items are cut, and each
kept item carries its risk-fix. Everything here **extends** the approved `/work` + unpin
design and **reuses** its helpers — no duplication. Zero new third-party deps.

## Spine: `notifications/commands.py` (NEW, pure, discord-free)

The single source of truth that kills today's duplicated `!`-grammar (parsed in two
divergent dialects: `command_bot.handleCommand` via exact-token split vs
`orchestrator._translateDiscord` via `startswith()`, where `!skipfoo` wrongly matches
`skip` and `!add`'s `raw[4:]` mis-slices). Exposes:

- `COMMAND_REGISTRY: dict[str, dict]` — canonical list (`abort, pause, resume, approve,
  reject, skip, add, retry, status, plan, log, help`) with `{arg, help, mutating}`.
- `Command` (NamedTuple `name, arg`) + `parseCommand(content) -> Command | None` —
  exact-token match on `parts[0].lower()` via `split(maxsplit=1)`; `None` for non-`!`
  or unknown. `skip` arg validated against `^st-\d{3}$`.
- `applyCommand(bus, state, cmd) -> str` — performs the bus mutation and returns
  **well-formatted markdown text** (never an embed — see risk note) for read commands
  (`status/plan/log/help`), `""` for pure control ops. Verb computed explicitly
  (`approved`/`rejected`, never `cmd[1:]+"d"` which produced `rejectd`). One `NO_TASK`
  constant.
- `decide(author_id, is_bot, content) -> Command | None` — the **shared gate** used by
  BOTH the gateway and the orchestrator poller: returns the command to apply only if the
  author is authorized and not a bot. Pure → directly unit-testable (covers the
  stale-replay/authorization regression without a live gateway).
- `isAuthorized(user_id: int | None) -> bool` — `True` when `DISCORD_HUMAN_USER_ID` is
  unset **or blank** (empty-string guard — it's read from `.env`); else
  `user_id is not None and user_id == int(<id>)`. The approved `command_bot._isAuthorized`
  and `work_launcher` delegate here; the policy can never diverge.
- `resolveTargetTask() -> TaskState | None` (wraps `loadLatest`) + `ACTIVE_STATUSES` +
  `isRunActive(state) -> bool`. **`work_launcher.activeRun()` calls `isRunActive`** (not
  a 4th definition of "active"). `ACTIVE_STATUSES` is derived as "all statuses minus
  `TaskState._TERMINAL`" so it can't drift from the terminal set.

`command_bot.handleCommand` and `orchestrator._translateDiscord` become thin callers of
`decide` + `parseCommand` + `applyCommand`.

## `notifications/discord_bot.py`

- **One REST chokepoint** `_request(method, path, *, json=None, params=None, retries=DISCORD_RETRY_MAX)`
  → `requests.Response | None`. Folds the config guard, `_authHeaders`, base URL,
  `timeout=DISCORD_REST_TIMEOUT`, success band, and logging that the 6 helpers each
  duplicate today. On **429** it reads `retry_after` (body, then `Retry-After` header),
  sleeps `min(retry_after, 10)`, retries up to `retries`.
  - **Risk-fix (control loop must stay responsive):** `fetchMessagesAfter` (orchestrator
    poller only) calls `_request(..., retries=0)` → a 429 returns immediately exactly
    like today; retries/backoff apply **only to milestone sends + dashboard edits**, never
    to the abort/pause poll path.
  - **Risk-fix (no global mute):** a hard **401** (bad token) logs ERROR once and latches
    a module `_disabled` flag; **403/404 never disable** (404 = a deleted message is
    normal). The 8-hour run can't go dark from one transient error.
  The 6 public helpers (`createMessage/editMessage/pinMessage/fetchMessagesAfter/
  sendEmbed/_post`) become thin payload-builders over `_request`.
- **`unpinMessage(message_id) -> bool`** (approved) — `_request("DELETE", …)`, treats
  **404 = success** (idempotent). `pinMessage`: on a 400 whose body mentions the pin cap,
  log a distinct actionable ERROR.
- **Embed safety at the boundary** `_clampEmbed(embed)` called inside
  `createMessage/editMessage/_post`: per-field clamp (name→256, value→1024, desc→4096),
  drop fields beyond 25. This fixes the real bug (an unbounded `pr_val`/`doc_path` field
  >1024 currently 400s the **whole** complete/architect milestone, silently losing it).
  - **Risk-fix (don't degrade the live dashboard):** the 6000-total enforcement does
    **not** drop trailing fields (which would silently delete the dashboard's dynamic
    "Recent events"/"Last verify" rows mid-run). It trims the **largest field values
    first** with a visible `…` marker, preserving row structure.
  `truncate(text, n)` (returns `text[:n-1].rstrip()+"…"` when clipped) routes the existing
  ad-hoc slices so clipping is always marked.
- **Owner-only mentions.** Drop the hardcoded `@everyone` in `sendBlocked` →
  `content = humanPing()` only. Default `allowed_mentions = {"parse": [], "users":
  [owner] if owner else []}` so the bot can never mass-ping.
  - **Risk-fix:** only set `allowed_mentions` when `content` is truthy; `editMessage`
    (dashboard PATCH, no content) must **not** inject it. (`DISCORD_BROADCAST_SEVERE` flag
    from the raw synthesis is **cut** — YAGNI for a solo private server.)
- **`formatVerdict` allowlist.** `APPROVED = {approved, approve, pass, ok}`,
  `CHALLENGED = {challenged, rejected, reject, blocked, fail}`, else `❔ UNKNOWN` (neutral
  grey `0x95A5A6` in `adversaryTriggeredEmbed`, not green). *Severity downgraded to low:*
  the adversary is a Phase-1 stub that always returns `approved`, so this is correctness
  insurance for Phase 2, not an active bug.
- **`fetchMessagesAfter` returns `author_id`** (`str((m.author or {}).get("id") or "")`)
  so the orchestrator poller can authorize. Add **`baselineLatestId() -> str | None`**
  (GET `limit=1`, returns newest id, no messages) to seed the cursor. **Single-page only**
  (paging-until-`<limit` is **cut** — a >25-message burst between 4s polls is implausible
  for a solo channel and synchronous paging would stall the control loop).

## `notifications/dashboard.py`

- **Deadlock-free thread safety.** `update()` must never acquire the orchestrator's
  `_state_lock` while holding (or being held under) `DiscordDashboard._lock` — the AB/BA
  the critique flagged. Design: the dashboard holds an optional reference to the
  orchestrator lock (set in `start()`); `_embed` acquires it **briefly** to copy
  `list(state.subtasks)` + read scalar meta into locals, **releases it**, then builds the
  embed, then acquires a separate `self._send_lock` only around the `editMessage` network
  call. Strict order (state-lock → release → send-lock), and no `update()` call site holds
  `_state_lock` today, so no nesting. This kills the "list changed size during iteration"
  crash that can mark a good subtask failed, and serializes overlapping PATCHes.
- **Recover-once.** Capture `editMessage`'s bool: on a hard 404 (dashboard deleted) clear
  `message_id` and recreate **exactly once** (guarded by `self._recreated`) so a persistent
  `createMessage` failure can't spawn many pins; transient failure leaves `message_id`
  intact and just logs. Preserves the ONE-embed contract.
- **`unpin()`** (approved) — `try/except`, idempotent, never raises.
- **Density/professionalism.** Drop the redundant `Status` field (the title already
  carries the phase) or map raw status → friendly label; merge the 5-char Effort bar onto
  the Replans/Adversary inline row; drop the placeholder `L3` (relabel `Mode: watch`);
  derive the footer help from `COMMAND_REGISTRY` (can't go stale) and make it
  context-aware (`!resume` when paused, `!approve/!reject` when a gate is pending); event
  timestamps use `datetime.now().astimezone()` (tz-aware, matches the native-timestamp
  convention).

## `notifications/command_bot.py`

- **Authorize before dispatch.** `on_message`: `if not commands.isAuthorized(author.id):
  return` (+ log; plain messages can't get ephemeral replies) and optionally require
  `channel.id == DISCORD_CHANNEL_ID` (no DMs/other channels drive the bus).
  `on_interaction`: `defer(ephemeral=True)` then auth-check → `followup` "not authorized"
  **before** any bus mutation. Closes the hole where any member could `!abort` an 8-hour
  run or `!approve` a gate.
- **3s ack.** `on_interaction` `defer(ephemeral=True)` **immediately**, then run the (pure,
  sync) `handleButton`, then `followup.send(..., ephemeral=True)` — same pattern as `/work`.
- **Thin shells.** `handleCommand` = `parseCommand` → `resolveTargetTask` → `applyCommand`.
  `MAX_REPLY_CHARS = DISCORD_MAX_CONTENT - 100`. `on_interaction` branches on
  `interaction.type`: `component` → `handleButton`; `application_command` → the approved
  `/work` slash entry.
- **Professional copy.** All ack strings come from `applyCommand` as
  `"<emoji> <Capitalized>."`. `!status`/`!plan` replies are **rich markdown text**
  (progress bar, numbered `✅/⚡/⬜/❌` checklist, `relTime` for live/localized
  durations) — kept as text, **not** embeds, to avoid the missing-`Embed Links`-permission
  failure mode the critique raised (text always renders).
- **No leak.** The catch-all replies `"internal error (see logs)"` + `LOG.exception(...)`;
  never echoes raw exception text/paths to the channel.

## `orchestrator.py`

- **`_translateDiscord` hardening** (this is a SECOND un-authorized control path with the
  same stale-replay bug). At run start, seed the cursor **only when unseeded**:
  `if bus.getSeen() is None: bus.setSeen(discord.baselineLatestId())` — a best-effort,
  config-guarded, non-fatal call (never delays/breaks run start; **does not clobber a
  resumed run's mid-run cursor** — critique fix). In the loop: for each fetched message use
  `commands.decide(int(author_id) if author_id else None, is_bot, content)`; if it returns
  a command, `commands.applyCommand(bus, state, cmd)` (discard reply). Deletes the local
  `startswith` ladder — fixes `!skipfoo`/`!add`-slice/read-drift for free and shares one
  auth policy.
- **Named milestone embeds.** Move the four ad-hoc inline embeds (gate-needed,
  subtask-failed, aborted, self-ref) into builders that go through the shared template
  (leading-emoji title, `statusColor(<phase>)` — correct aborted-maroon `0x992D22` instead
  of raw `_RED`, `_nowIso()` timestamp, `footer {text: task <id8>}`). Delete the local
  `_YELLOW/_ORANGE/_RED`.
- **`dashboard.unpin()` in `runFull`'s `finally`** (approved).

## `config.py`

- Add `DISCORD_MAX_CONTENT=2000`, `DISCORD_MAX_EMBED_DESC=4096`,
  `DISCORD_MAX_FIELD_VALUE=1024`, `DISCORD_MAX_FIELD_NAME=256`,
  `DISCORD_EMBED_TOTAL_MAX=6000`, `DISCORD_REST_TIMEOUT=15`, `DISCORD_RETRY_MAX=2`.
  Reference these at every truncation/timeout site. Move the duplicated `_EFFORT_LABELS`
  here next to `EFFORT_BARS` (the EFFORT_META 3-key registry rebuild is **cut** — over-
  abstraction for 6 static rows). (`DISCORD_GUILD_ID` already added by the `/work` spec.)

## New files

- `notifications/commands.py` — the spine above.
- `tests/test_commands.py` — `parseCommand` exact-token (`!skipfoo` rejected, `!add`/`!skip`
  arg slicing), `st-id` regex, `applyCommand` mutations + copy (no `rejectd`),
  `isAuthorized` (unset/blank → allow; set → owner-only; blank-string no crash),
  `isRunActive` across terminal/non-terminal, **and `decide()` stale-replay/authorization
  regression** (unauthorized or bot author → `None` → no mutation).
- `tests/test_discord_rest.py` — `_request` 429 `retry_after` backoff (monkeypatched
  `requests`), 401-disables / 404-does-not, `_clampEmbed` limits + largest-first total
  trim, `truncate` ellipsis, `unpinMessage` 404=success, `formatVerdict` unknown→UNKNOWN,
  `fetchMessagesAfter` surfaces `author_id`, `baselineLatestId` is cursor-seed-only.

## Cut (audit items rejected per critique — recorded so they're not silently dropped)

- `notifications/embeds.py` file split + re-export shim — mechanical churn, no functional
  gain; pure builders stay in `discord_bot.py`, `/work` modal/dropdown builders live in
  `command_bot.py`.
- `DISCORD_BROADCAST_SEVERE` gated-`@everyone` path — YAGNI for a solo private server.
- `fetchMessagesAfter` multi-page paging — implausible burst + would stall the control loop.
- `EFFORT_META` registry consolidation — over-abstraction; just relocate `_EFFORT_LABELS`.

## Out of scope (noted follow-ups, not part of this Discord pass)

- `webdash.py` CSRF/token hardening — it's a sibling control surface, not Discord; the
  full token+constant-time plumbing is gold-plating for a 127.0.0.1 solo server (critique).
  A lightweight `Origin`/`Host` check could be a later small follow-up.
- `verifier.py` argv-not-shell for repaired verifies — defense-in-depth whose entry point
  (attacker-controlled `!add`) is **closed by the auth fixes here**; revisit only as a
  clean 3-line swap later.

## Revised sequencing (build order)

1. `config.py` constants (`DISCORD_*` limits/timeout/retry, relocate `_EFFORT_LABELS`).
2. `notifications/commands.py` (pure) + `tests/test_commands.py` — no wiring yet.
3. `discord_bot.py` transport: `_request` chokepoint (429 + 401-only-disable), rewrite 6
   helpers, `unpinMessage`, `_clampEmbed`/`truncate` + `tests/test_discord_rest.py`.
4. `discord_bot.py` behavior: `formatVerdict` allowlist; owner-only `allowed_mentions`
   (content-only); `fetchMessagesAfter` `author_id` + `baselineLatestId` (single page).
5. `notifications/work_launcher.py` + `tests/test_work_launcher.py` (the approved core;
   `activeRun` delegates to `commands.isRunActive`).
6. `command_bot.py`: delegate to `commands.py`; authorize-before-dispatch; defer→followup
   ephemeral; `application_command` branch + the `/work` slash command, `WorkModal`,
   `WorkSetupView`; sync-once + guild fallback; `tree.on_error`; generic error reply.
7. `orchestrator.py`: seed cursor once via `baselineLatestId`; `_translateDiscord` →
   `commands.decide`/`applyCommand`; four named milestone embeds (delete `_RED/_ORANGE/
   _YELLOW`); `dashboard.unpin()` in `finally`.
8. `dashboard.py`: deadlock-free snapshot + `_send_lock`; recover-once; `unpin()`;
   density/footer/timestamp cleanups.
9. Final verification: all unit tests green; import-smoke `command_bot`; manual live smoke
   (`/work` end-to-end, `!abort` from a non-owner is ignored, dashboard unpins on finish).
