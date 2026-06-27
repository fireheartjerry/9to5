# 9TO5 — Notification System Reference

> **Scope:** All notification surfaces, the `NotificationBus` fan-out layer,
> the `NotificationEntry` schema, Discord dashboard and milestones, branding /
> design system, slash commands, web dashboard, gateway command bot, audit log,
> and metrics.  Reflects the state after the st-006 hardening pass and
> subsequent surface additions (audit, metrics, slash, branding, views,
> work_launcher).

---

## Architecture overview

```
Orchestrator / subtask boundary
        │
        ▼
 NotificationBus.emit(event_type, payload)
        │
        ├──▶ DiscordDashboard.handle()   ── PATCH the pinned live embed
        ├──▶ DiscordMilestone.handle()   ── POST discrete milestone embeds
        └──▶ WebdashSurface.handle()     ── write latest snapshot (1 s TTL)

Orthogonal surfaces (not registered on the bus):
  notifications/command_bot.py  ── discord.py gateway bot; slash + ! commands
  orchestrator.py REST poll      ── inline ! command handling (no bot needed)
  notifications/audit.py         ── file-backed control-action audit log
  notifications/metrics.py       ── aggregate run metrics from task-state store
```

All surfaces are **isolated**: an exception inside one surface is caught, logged
at WARNING, and never propagates into the orchestrator run loop.

---

## NotificationBus (`notifications/bus.py`)

### Purpose
Single fan-out point.  Register surfaces once; emit events to all of them.

### Protocol
Any object with a `handle(event_type: str, payload: dict) -> None` method is a
valid surface.  The `NotificationSurface` protocol (`@runtime_checkable`) makes
this explicit — `isinstance(obj, NotificationSurface)` works at runtime.

### Usage

```python
from notifications.bus import NotificationBus

bus = NotificationBus()
bus.register(my_discord_surface)
bus.register(my_web_surface)

# Emit from anywhere in the orchestrator
bus.emit("subtask_done", {"subtask_id": "st-003", "title": "Add tests"})
```

### Isolation contract
A surface that raises **never** stops downstream surfaces and **never** raises
into the caller.  Every surface error is logged:

```
WARNING notifications.bus: surface <DiscordDashboard …> raised on event 'subtask_done' — suppressed
```

### Error handling

#### Surface isolation contract

`emit()` wraps every `surface.handle()` call in a `try/except BaseException`
block.  A surface that raises — for any reason — is logged and skipped; all
remaining surfaces still receive the event, and the caller never sees the error.

```python
except BaseException:  # surface errors must never reach callers
    _log.exception("surface %r raised on event %r — suppressed", surface, event_type)
```

The logger name is `notifications.bus`, level `WARNING`.  Error output follows
the stdlib `logging.exception()` format so the full traceback is captured.

#### KeyboardInterrupt and SystemExit inside a surface

`BaseException` (not `Exception`) is caught deliberately.  This means
`KeyboardInterrupt` and `SystemExit` raised *inside* a surface's `handle()`
method are also suppressed per-surface.

**Why:** a surface must never be able to kill the orchestrator run loop.  Doing
`sys.exit()` or pressing Ctrl-C while a surface is executing cannot cause the
run to abort.

**Implication for surface authors:** do not rely on `KeyboardInterrupt` or
`SystemExit` propagating out of `handle()` — they won't.  Graceful shutdown
signals must flow through `ControlBus`, not through exceptions raised inside
surfaces.

#### What is NOT suppressed

Errors raised **before** `emit()` reaches the per-surface loop — e.g. a
`TypeError` from passing wrong argument types to `emit()` — propagate normally
to the caller.  Only per-surface exceptions are swallowed.

#### Logging behaviour

| Condition | Log level | Logger |
|-----------|-----------|--------|
| Surface raises any `BaseException` | `WARNING` (with traceback via `exception()`) | `notifications.bus` |
| Normal emission (no errors) | *(silent)* | — |

To capture bus error output in tests or production:

```python
import logging
logging.getLogger("notifications.bus").setLevel(logging.WARNING)
```

#### Expected tracebacks in test output

When running `test_notification_bus.py`, you will see tracebacks printed to
stderr for every test that intentionally raises inside a surface.  **This is
correct behaviour**, not a failure signal.  Each traceback comes from
`logging.exception()` inside `bus.py`'s `emit()` loop — it records the full
stack of the suppressed exception.  The tests still pass (`OK`) because the
exception never reaches the caller.

Example (expected — not an error):

```
surface <_RaisingSurface …> raised on event 'replan' — suppressed
Traceback (most recent call last):
  …
ValueError: bad surface
```

Tests that assert on logging (e.g. `test_error_logged_as_warning`) use
`assertLogs("notifications.bus", …)` which temporarily captures and suppresses
the handler, so those tests produce no visible traceback.

To silence bus tracebacks globally during a test run, disable the logger before
the suite starts:

```python
import logging
logging.getLogger("notifications.bus").disabled = True
```

Re-enable it before any test that asserts on log output.

#### Running the bus test suite

The acceptance test can be invoked directly or via the standard test runner:

```bash
# Direct invocation (uses sys.path.insert in the test file to locate the package)
python C:\9to5\tests\test_notification_bus.py

# Via unittest runner (no sys.path manipulation needed — runner sets PYTHONPATH)
python -m unittest tests.test_notification_bus
```

The `sys.path.insert(0, ...)` at the top of the test file is present solely to
support the direct-invocation form used by the acceptance check.  When using
`python -m unittest` or `pytest` from the project root, the package is already
on `sys.path` and the insert is a no-op.

#### surface_count helper

`bus.surface_count` returns the number of registered surfaces.  Use it in
tests or health checks to confirm surfaces were registered before emitting:

```python
assert bus.surface_count == 2, "expected discord + web surfaces"
```

### Anti-patterns
- Do **not** make `NotificationBus` a module-level singleton imported at run
  start.  Instantiate one per run so surfaces can be re-registered cleanly on
  restart.
- Do **not** `bus.emit()` inside a surface's own `handle()` — recursive
  emission is not guarded.
- Do **not** raise from `handle()` to signal failure — the exception is
  suppressed; use an out-of-band mechanism (e.g. a shared flag, a `ControlBus`
  write) if a surface needs to communicate a fatal condition.

---

## NotificationEntry schema (`notifications/entry.py`)

Every entry written to `state.data["notifications"]` must be produced by
`makeEntry()` so the schema is guaranteed.

### Required keys

| Key | Type | Description |
|-----|------|-------------|
| `at` | ISO-8601 string (UTC) | Timestamp, set automatically by `makeEntry` |
| `kind` | non-empty `str` | Event kind from `VALID_KINDS` (or a custom string) |
| `detail` | `str` | Human-readable description |

### Canonical `kind` vocabulary

```
plan_gate           plan_challenged       architecture_challenged
subtask_failed      subtask_crashed       subtask_done
adversary_triggered backfill              replan
replan_removed      architect_done        planning_start
selfmod_gate        pr_held               complete
aborted             blocked
```

Custom kinds are permitted — only the three required keys are enforced.

### API

```python
from notifications.entry import makeEntry, validate, isValid, VALID_KINDS

# Create an entry
entry = makeEntry("replan", "added 2 subtasks after verifier failure")

# With extra fields
entry = makeEntry("subtask_done", "tests pass", subtask_id="st-003")

# Validate an arbitrary dict
errors = validate(entry)   # [] means valid
ok = isValid(entry)        # True iff validate() returns []

# Write to task state
state.data.setdefault("notifications", []).append(entry)
state.save()
```

### Validation errors returned by `validate()`

- `"missing required key: 'at'"` — key absent
- `"'at' is not valid ISO-8601: …"` — unparseable timestamp
- `"'kind' must be a non-empty string"` — empty or non-string kind
- `"'detail' must be a str, got …"` — wrong type

---

## Discord live dashboard (`notifications/dashboard.py`)

### Behaviour
One embed is created at run start and **PATCH-edited in place** on every step
boundary — never spams new messages.  It is pinned to the channel so it
floats at the top.  A rolling deque of 10 timestamped events forms the
"Recent events" field.

### Fields in every update

| Field | Content |
|-------|---------|
| Title | `{emoji} 9TO5 · {phase}` |
| Description | Goal (truncated to 240 chars) + progress bar + subtask tracker |
| Model | Active model ID |
| Mode | `watch` or `gated` |
| Elapsed | Human duration since run start (e.g. `1h 23m`) |
| ETA | Estimated remaining time based on current pace |
| Replans | Count of `replan` entries in `notifications` |
| Adversary | Count of adversary reviews |
| Effort | Visual effort bar |
| Current subtask | `` `st-NNN` title (attempt N)`` |
| Working dir | `meta.work_dir` |
| Last verify | `✅/❌ st-NNN — <cmd or expect>` |
| Recent events | Rolling 10-item deque with `HH:MM` timestamps |
| Footer | `task <id[:8]> · web :<port> · <control hint>` |

### Control-panel button row
The dashboard embed carries a two-row component panel (from `branding.controlPanelRow()`):

- Row 1: **Pause · Resume · Approve**
- Row 2: **Reject · Skip · Abort**

Button presses are handled by `views.ControlPanelView` in the gateway bot and
map to the same `ControlBus` signals as the corresponding slash / `!` commands.

### Lifecycle

```python
dash = DiscordDashboard()

# Run start — creates and pins the embed; restores event ring on resilience restart
dash.start(state, phase="starting", state_lock=rw_lock)

# After each step boundary
dash.update(state, phase="executing", note="st-003 verify passed",
            effort="high", model="claude-sonnet-4-6")

# Run end — remove pin (idempotent; never raises)
dash.unpin()
```

### Resilience restart behaviour
If `meta.dashboard_message_id` is set, `start()` attempts to edit the existing
embed rather than creating a new one, preventing duplicate pinned dashboards.

| `editMessageResult` return value | Behaviour |
|---|---|
| `"ok"` | Reuse the existing message |
| `"transient"` (429 / timeout) | Reuse message ID without recreating |
| `"not_found"` (genuine 404) | Create a fresh embed (once; one-shot guard) |

---

## Discord milestone embeds (`notifications/discord_bot.py`)

Milestone embeds are **new messages**, not edits to the dashboard.  They mark
irreversible transitions; the run continues immediately after posting.

### Embed builders

| Builder | When fired |
|---------|-----------|
| `planningStartEmbed(goal, subtasks)` | Planning complete |
| `architectDoneEmbed(doc_path)` | `architect.md` written |
| `adversaryTriggeredEmbed(title, reason, verdict)` | Adversary review done |
| `subtaskFailedEmbed(id, title, verify_result, attempts)` | Subtask exhausted retries |
| `completeEmbed(state, pr_link, elapsed)` | Run complete |
| `abortedEmbed(reason, elapsed)` | Run aborted |
| `blockedEmbed(reason, question)` + `blockedComponents()` | Human decision required |
| `gateNeededEmbed(gate)` | Gated-mode approval needed |
| `noticeEmbed(reason)` | Informational (fallback taken, horizon reached, etc.) |
| `selfRefEmbed(branch, protected)` | Self-referential run detected |

### Night mode
`sendEmbed(..., milestone=True)` is suppressed when `NIGHT_MODE=true` in `.env`
so unattended overnight runs do not spam the channel.

### 429 circuit breaker
`_RATE_LIMITED_UNTIL` is a module-level monotonic deadline.  Any call that hits
a 429 response arms the breaker for `retry_after` seconds (capped at 60 s).
All subsequent REST calls (across all surfaces and threads) short-circuit until
the window passes.  A hard 401 latches `_DISABLED = True` for the process
lifetime.

### `editMessageResult` return values
Used by `dashboard.py` to distinguish transient Discord failures from genuine
message deletion:

| Value | Meaning |
|-------|---------|
| `"ok"` | PATCH succeeded (2xx) |
| `"not_found"` | Message genuinely gone (404) — safe to recreate |
| `"transient"` | Network/429/5xx — do NOT recreate; retry next tick |

---

## Discord branding / design system (`notifications/branding.py`)

Pure (no network).  Provides the 9TO5 brand identity and polished embed
builders used by slash commands and the status surface.

### Key builders

| Function | Description |
|----------|-------------|
| `brandEmbed(title, ...)` | Branded embed with author, footer, brand colour |
| `statusEmbed(state, bus, uptime)` | Live run-status summary |
| `planEmbed(state, page, per)` | Paginated subtask list |
| `runsEmbed(summaries, page, per)` | Paginated recent-runs list |
| `runEmbed(state)` | Single-run detail |
| `helpEmbed()` | Full slash-command reference |
| `diagnosticsEmbed(checks)` | Health-check results |
| `metricsEmbed(m)` | Aggregate run metrics |
| `pingEmbed(latency_ms, uptime, version)` | Gateway latency / uptime |
| `auditEmbed(entries)` | Recent control-action audit log |
| `controlPanelRow()` | Two action rows (Pause·Resume·Approve / Reject·Skip·Abort) |

---

## `/loop` command — correct usage and best practices

`/loop is a CC slash command` (Claude Code native).  It is handled entirely by
the Claude Code CLI process — **not** by the 9TO5 Python orchestrator.

### What `/loop` does

Runs a prompt or slash command on a recurring interval.  When no interval is
given the model self-paces via `ScheduleWakeup`.

```
/loop 5m /babysit-prs           # every 5 minutes
/loop /check-deploy             # self-paced (model chooses the interval)
```

### Error handling inside a loop body

Loop bodies execute in a standard Claude Code turn.  Transient errors do not
stop the loop — the next interval fires regardless.  For hard failures you want
to surface, emit a notification from inside the loop task:

```python
# inside a loop-triggered orchestrator task
try:
    result = execute_step()
except Exception as exc:
    bus.emit("subtask_failed", {"error": str(exc), "attempts": 1})
    raise   # re-raise so the loop body's exit code is non-zero
```

### Retry mechanisms with `retryTask`

Use `retryTask` (see [Orchestrator error handling](#orchestrator-error-handling))
to auto-retry unstable operations before the failure bubbles up:

```python
from error_handling import retryTask, MAX_RETRIES

# Up to MAX_RETRIES (default 3) attempts; raises RetryExhausted on exhaustion
result = retryTask(fetch_external_data, args=(url,))

# With an alert callback — returns {"ok": False} instead of raising
result = retryTask(
    fetch_external_data,
    args=(url,),
    max_retries=MAX_RETRIES,
    on_alert=lambda msg, n: bus.emit("subtask_failed", {"error": msg, "attempts": n}),
)
if not result["ok"]:
    # handle gracefully — alert already fired
    ...
```

### Anti-patterns

| Wrong | Right |
|-------|-------|
| `subprocess.run(["claude", "/loop", ...])` | Type `/loop` directly in Claude Code |
| Calling `/loop` from a 9TO5 orchestrator Python function | `/loop` is a CLI-level feature; use `retryTask` for programmatic retry |
| Swallowing all exceptions in a loop body | Re-raise or emit `subtask_failed` so the orchestrator can track failures |

---

## Slash commands (`notifications/slash.py`)

> **Important:** `/loop is a CC slash command` (Claude Code native) — do not
> invoke it via subprocess or shell script.  It is handled by the Claude Code
> CLI process itself, not by the 9TO5 Python orchestrator, and calling it via
> `subprocess.run(["claude", "/loop", ...])` or similar will not work as
> intended.  All other slash commands below are Discord application commands
> registered in the gateway bot.

Registered onto a `discord.app_commands.CommandTree` by
`slash.registerSlashCommands(tree, client, started_at)`.  All read commands are
open; mutating commands require the configured owner and enforce a rate-limit
cooldown (`COOLDOWN_RATE` / `COOLDOWN_PER` from config).

### Full command list

| Command | Mutating | Description |
|---------|----------|-------------|
| `/status` | No | Current phase, subtask X/Y, elapsed/ETA |
| `/plan [page]` | No | Paginated subtask list |
| `/log` | No | Obsidian index + web dashboard URL |
| `/help` | No | Full command reference |
| `/runs [page]` | No | List recent runs |
| `/run <id>` | No | Inspect a run by task ID |
| `/ping` | No | Gateway latency, uptime, version |
| `/diagnostics` | No | Environment health checks |
| `/metrics` | No | Aggregate run metrics |
| `/audit` | No | Recent control actions |
| `/work [goal] [horizon]` | Yes | Launch a new run (guided if no args) |
| `/resume [id]` | Yes | Resume a paused run (or unpause the active one) |
| `/abort` | Yes | Graceful stop after the current step |
| `/pause` | Yes | Hold the run |
| `/approve` | Yes | Approve the pending gate |
| `/reject` | Yes | Reject the pending gate |
| `/skip <id>` | Yes | Skip a pending subtask |
| `/add <title>` | Yes | Queue a new subtask |
| `/retry` | Yes | Re-run the current subtask |

Mutating commands are audited: `audit.record(user_id, command_name, task_id,
"slash")` is called for every mutating slash-command invocation.

---

## Web dashboard (`notifications/webdash.py`)

### Routes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Auto-refreshing dark HTML status page |
| `GET` | `/api/state` | JSON snapshot `{meta, subtasks, progress, control}` |
| `POST` | `/api/control` | `{action, arg}` — writes to `ControlBus` |

### Control actions via web

```json
{"action": "abort"}
{"action": "pause"}
{"action": "resume"}
{"action": "approve"}
{"action": "reject"}
{"action": "skip", "arg": "st-004"}
```

All actions write to `state/control/<task_id>.json`.  They take effect at the
next `ControlBus.check()` call inside the run loop.

### Snapshot TTL cache
`/api/state` caches the full `TaskState` snapshot for 1 second (monotonic
clock).  Under rapid browser refresh or concurrent polling this avoids repeated
JSON-parse + disk reads.  Different `task_id` values always miss the cache.

### Start/stop
The web dashboard is started by the orchestrator as a daemon thread and dies
with the process.  Default: `127.0.0.1:8787`.  Override with
`WEB_DASHBOARD_PORT` in `.env`.

---

## Gateway command bot (`notifications/command_bot.py`)

A `discord.py` gateway bot providing lower-latency command handling than the
inline REST poll.  Registers slash commands (`slash.py`) and persistent
component views (`views.py`).

### ! text commands

| Command | Effect |
|---------|--------|
| `!status` | Post current run status embed |
| `!plan` | Post current subtask list |
| `!log` | Post Obsidian index + web dashboard URL |
| `!abort` | Write `abort` to `ControlBus` |
| `!pause` | Write `pause` to `ControlBus` |
| `!resume` | Write `resume` to `ControlBus` |
| `!approve` | Write `approve` to `ControlBus` (gate decision) |
| `!reject` | Write `reject` to `ControlBus` (gate decision) |
| `!skip <id>` | Write `skip` for the given subtask ID (format: `st-00N`) |
| `!add <title>` | Insert a new pending subtask |
| `!retry` | Re-run the current subtask |
| `!help` | Show command list |

Authorization: only the configured `DISCORD_HUMAN_USER_ID` may issue mutating
commands.  Bot messages are always ignored.

### Run (optional)
The orchestrator polls the channel between steps so `!commands` work from
`main.py` alone — the gateway bot provides faster response but is not required.

```
python -m notifications.command_bot
```

### Interactive button actions
`blockedComponents()` renders **Answer / Skip / Abort** buttons (`sc_answer`,
`sc_skip`, `sc_abort`).  `branding.controlPanelRow()` renders the persistent
**Pause · Resume · Approve / Reject · Skip · Abort** panel on the live
dashboard.  Both are handled by `views.ControlPanelView`.

---

## Audit log (`notifications/audit.py`)

File-backed JSON-lines log of every control command issued.  Location:
`config.AUDIT_LOG_PATH`.  Size-rotated at `config.AUDIT_MAX_BYTES`.

### Schema

```json
{
  "at":      "2026-06-24T10:00:00+00:00",
  "user_id": "123456789",
  "action":  "abort",
  "task_id": "b29a4edf…",
  "detail":  "slash"
}
```

### API

```python
from notifications.audit import record, recent

# Write (best-effort; never raises)
record(user_id, "abort", task_id=state.task_id, detail="slash")

# Read last N entries (oldest-first)
entries = recent(n=20)
```

---

## Metrics (`notifications/metrics.py`)

Aggregate statistics computed from the task-state JSON store.  Pure (reads
files only; no network).

### `compute()` return shape

```python
{
    "total_runs":           int,
    "by_status":            dict[str, int],   # status → count
    "terminal_runs":        int,
    "success_runs":         int,
    "success_rate":         float | None,     # success / terminal
    "avg_duration_seconds": float | None,
    "subtasks_total":       int,
    "subtasks_passed":      int,
}
```

---

## Embed size limits

Discord enforces hard limits.  `_clampEmbed()` in `discord_bot.py` enforces
them before every send or edit so a single oversized field never drops the
whole embed.

| Limit | Value |
|-------|-------|
| `description` | 4 096 chars |
| Field `name` | 256 chars |
| Field `value` | 1 024 chars |
| Total embed char count | 6 000 |
| Fields per embed | 25 |

Clamp strategy: clamp each field individually first, then shrink the **largest**
field value iteratively until the total is ≤ 6 000.

---

## Orchestration workflow integration

This section maps each orchestrator phase to the notification events it emits,
the surfaces that handle them, and the decision points that govern routing.

### Phase-by-phase event map

| Phase | Event emitted | Surfaces triggered |
|-------|---------------|--------------------|
| Planning start | `planning_start` | Dashboard (update), Milestone (new embed) |
| Architect done | `architect_done` | Dashboard (update), Milestone (new embed) |
| Subtask begin | `subtask_started` | Dashboard (update) |
| Verifier pass | `subtask_done` | Dashboard (update), `NotificationEntry` appended |
| Verifier fail + retry | `subtask_failed` | Dashboard (update), Milestone if attempts exhausted |
| Adversary triggered | `adversary_triggered` | Dashboard (update), Milestone (new embed) |
| Replan | `replan` | Dashboard (update), `NotificationEntry` appended |
| Run complete | `complete` | Dashboard (update), Milestone (new embed) |
| Run aborted | `aborted` | Dashboard (update), Milestone (new embed) |

### Step-by-step: subtask execution with notification emissions

```python
# orchestrator.py — simplified subtask loop showing decision points

for subtask in pending_subtasks:
    # 1. Announce start
    bus.emit("subtask_started", {"subtask_id": subtask["subtask_id"], "title": subtask["title"]})
    dash.update(state, phase="executing", note=f"running {subtask['subtask_id']}")

    attempt = 0
    while attempt < MAX_SUBTASK_ATTEMPTS:
        attempt += 1

        # 2. Execute (Claude Code CLI subprocess)
        output = executor.run(subtask, attempt)

        # 3. Decision point: run the verifier
        verify_result = verifier.check(subtask, work_dir)

        if verify_result.passed:
            # 4a. Success path — record entry, advance
            entry = makeEntry("subtask_done", f"{subtask['subtask_id']} verified OK")
            state.data.setdefault("notifications", []).append(entry)
            state.save()
            bus.emit("subtask_done", {"subtask_id": subtask["subtask_id"]})
            break
        else:
            # 4b. Failure path — retry or exhaust
            if attempt >= MAX_SUBTASK_ATTEMPTS:
                bus.emit("subtask_failed", {
                    "subtask_id": subtask["subtask_id"],
                    "verify_result": verify_result.detail,
                    "attempts": attempt,
                })
            # loop continues with re-authored prompt

    # 5. Decision point: adversary trigger check
    if adversary.shouldTrigger(output, attempt):
        verdict = adversary.review(subtask, output)
        bus.emit("adversary_triggered", {"verdict": verdict.status, "concerns": verdict.concerns})

    # 6. Decision point: check ControlBus before next subtask
    ctl = ControlBus.check(state.task_id)
    if ctl.abort:
        bus.emit("aborted", {"reason": ctl.reason})
        break
    if ctl.pause:
        # block here until resume signal
        ControlBus.waitForResume(state.task_id)
```

### Decision point reference

| Decision | Condition | Action |
|----------|-----------|--------|
| Emit milestone vs. dashboard-only | `milestone=True` on `sendEmbed()` | New Discord message (suppressed in `NIGHT_MODE`) |
| Retry subtask | `verify_result.passed == False` and `attempt < MAX_SUBTASK_ATTEMPTS` | Re-author prompt with failure detail; re-run executor |
| Exhaust retries | `attempt >= MAX_SUBTASK_ATTEMPTS` | Emit `subtask_failed` milestone; mark subtask `failed`; continue to next |
| Trigger adversary | Output contains trigger strings or heartbeat floor reached | Call `adversary.review()`; emit `adversary_triggered` |
| Abort run | `ControlBus.check().abort == True` | Emit `aborted`; exit loop |
| Resilience restart | `meta.dashboard_message_id` set | `dash.start()` edits existing embed; no duplicate pin |
| Night mode suppression | `NIGHT_MODE=true` in `.env` | `sendEmbed(milestone=True)` is a no-op |

### Wiring surfaces at run start

```python
# main.py / orchestrator.py — surface registration order matters for logging
bus = NotificationBus()

dash = DiscordDashboard()
milestone = DiscordMilestone()
webdash = WebdashSurface(state)

bus.register(dash)       # live embed — registered first; highest priority
bus.register(milestone)  # discrete embeds
bus.register(webdash)    # 1-second TTL JSON snapshot

# Start the web dashboard daemon thread
webdash.start()

# Kick off the live Discord embed (creates + pins)
dash.start(state, phase="starting", state_lock=rw_lock)
```

After this block, every `bus.emit()` call fans out to all three surfaces in
registration order.  A surface that raises is skipped; the others still receive
the event.

### Adding a custom surface

Any object with `handle(event_type: str, payload: dict) -> None` qualifies:

```python
class SlackSurface:
    def handle(self, event_type: str, payload: dict) -> None:
        if event_type in ("subtask_failed", "aborted", "complete"):
            slack_post(f"[9to5] {event_type}: {payload}")

bus.register(SlackSurface())
# from this point every emit() also calls SlackSurface.handle()
```

The `@runtime_checkable` `NotificationSurface` protocol means
`isinstance(obj, NotificationSurface)` returns `True` for any object that
implements `handle()`, which lets health checks confirm registration:

```python
from notifications.bus import NotificationSurface
assert isinstance(my_surface, NotificationSurface), "surface missing handle()"
assert bus.surface_count == 4, "expected 4 surfaces after adding Slack"
```

---

## Frontier Discord lab (branch `feat/discord-frontier-lab`)

An elevation of the surface above into a "frontier lab". Every new capability is
**flag-gated and defaults OFF** (`DISCORD_LAB_MODE` master switch + per-feature flags:
`DASHBOARD_CV2`, `CAST_MODE`, `ASK_ENABLED`, `POLL_GATES`, `RUN_THREADS`, `SCHEDULED_EVENTS`,
`AUTOMOD_GUARD`, `REACTION_APPROVE`, `WATCHDOG_ENABLED`, `VISUALS_ENABLED`, `COCKPIT_THEME`),
so default behaviour is byte-for-byte the legacy surface. The two-process split (loop-less
orchestrator REST + 4s control-poll | gateway), the global 429 breaker, owner-auth, and the
pure `commands.py` spine are all preserved.

### Gateway = a cog package
`notifications/command_bot.py` is now a back-compat shim over `notifications/bot/core.py`
(`NightclawBot`, a `discord.ext.commands.Bot`). `setup_hook` loads hot-reloadable cogs
(`/reload`), registers persistent views + a `DynamicItem`, and syncs the tree. Cogs:
`observe_cog` (status/plan/log/help/ping/diagnostics/metrics/audit), `control_cog`
(pause/approve/reject/retry/add/skip/abort), `runs_cog` (work/wipe/runs/run/resume),
`admin` (/reload /cockpit /hud), `ask_cog` (/ask), `plan_cog` (/plan-edit /timeline +
context menus), `engagement_cog` (Poll votes), `ops_cog` (reactions + watchdog).
`notifications/slash.py` is reduced to the shared helpers the command cogs use.

### Components V2 cockpit
`notifications/cv2.py` builds the live cockpit as a Components-V2 tree (Container/Section/
TextDisplay/MediaGallery/Separator + control buttons; flag `IS_COMPONENTS_V2 = 1<<15`).
`dashboard.py` renders it dual-path behind `DASHBOARD_CV2` — raw REST
(`discord_bot.createComponentsV2`/`editComponentsV2Result`, multipart via the extended
`_request`) on the orchestrator side, `LayoutView` on the gateway. `visuals.py` (Pillow)
draws the hero progress card / burndown / end-of-run replay GIF (throttled to ≤1 image
upload per `COCKPIT_IMAGE_MIN_INTERVAL`); `theme.py` is the palette/glyph/accent keystone;
`console_hud.py` renders an ANSI mission-console HUD.

### The Cast, Ask, engagement, ops
`personas.py` + `cast.py` route each agent's voice through a webhook identity
(`discord_bot.sendAs`) — incl. an Adversary duel VS-card. `ask.py` answers run questions
from the local Ollama brain (`/ask`). `engagement.py` maps native Poll votes
(`on_raw_poll_vote_add`) to `ControlBus.decide` for gated approvals. `ops.py` resolves a
gate from an owner super-reaction (`on_raw_reaction_add`) and runs a silence watchdog.

---

## Orchestrator error handling

The `error_handling` module (and its re-export `enhanced_error_handling`) provides
`retryTask` — a retry-before-alert wrapper for any callable inside the orchestrator.
Failed tasks are retried up to `MAX_RETRIES` times before the alert fires.

### `retryTask` — retry-before-alert

```python
from error_handling import retryTask, MAX_RETRIES, RETRY_DELAY_SECONDS, RetryExhausted

# Basic usage — raises RetryExhausted if all attempts fail
result = retryTask(my_function, args=(arg1, arg2))
# {"ok": True, "result": <return value>, "attempts": <n>}

# With an alert callback — returns {"ok": False, ...} instead of raising
def on_alert(error_msg: str, attempts: int) -> None:
    bus.emit("subtask_failed", {"error": error_msg, "attempts": attempts})

result = retryTask(
    my_function,
    kwargs={"key": "value"},
    max_retries=3,
    delay=1.0,
    on_alert=on_alert,
)
# {"ok": False, "error": "ValueError: ...", "attempts": 3}
```

### Key parameters and constants

| Name | Default | Description |
|------|---------|-------------|
| `MAX_RETRIES` | `3` | Default retry ceiling (auto-retries before alerting) |
| `RETRY_DELAY_SECONDS` | `1.0` | Sleep between attempts (seconds) |
| `on_alert` | `None` | Callback `(error_msg, attempts)` fired after exhaustion |

### Return shape

| Key | Condition |
|-----|-----------|
| `{"ok": True, "result": ..., "attempts": n}` | At least one attempt succeeded |
| `{"ok": False, "error": ..., "attempts": n}` | All failed, `on_alert` set |
| raises `RetryExhausted` | All failed, `on_alert` is `None` |

### Sleep-after-last-attempt guard

Sleep fires **only between attempts** (never after the final attempt) so no
unnecessary latency is added before the alert fires:

```python
if attempt < max_retries:   # explicit guard
    time.sleep(delay)
```

### Logging behaviour

| Event | Level | Logger |
|-------|-------|--------|
| Attempt failed | `WARNING` | `9to5.error_handling` |
| Recovered on later attempt | `INFO` | `9to5.error_handling` |
| All attempts exhausted | `CRITICAL` | `9to5.error_handling` |

### Import paths

```python
# Canonical
from error_handling import retryTask, MAX_RETRIES, RETRY_DELAY_SECONDS, RetryExhausted

# Deliverable alias (re-exports the canonical module identically)
from enhanced_error_handling import retryTask
```

---

## Conventions

- `ALL_CAPS` — module constants (`VALID_KINDS`, `REQUIRED_KEYS`, `CONTROL_PANEL_IDS`)
- `snake_case` — variables and parameters
- `camelCase` — functions (`makeEntry`, `progressBar`, `controlPanelRow`)
- `pathlib.Path` everywhere — never `os.path`
- All notification calls are best-effort — they must never halt the run loop
- Secrets (`DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`, etc.) live in `.env` only
- Night mode (`NIGHT_MODE=true`) suppresses milestone embeds for unattended runs
