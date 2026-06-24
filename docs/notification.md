# 9TO5 — Notification System Reference

> **Scope:** All notification surfaces, the `NotificationBus` fan-out layer,
> the `NotificationEntry` schema, the Discord dashboard, milestone embeds, web
> dashboard, and the gateway command bot.  This document reflects the state of
> the notification system after the st-006 hardening pass.

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
        └──▶ WebdashSurface.handle()     ── write latest snapshot (1s TTL)

Orthogonal:
  notifications/command_bot.py ── discord.py gateway bot; !commands
  orchestrator.py REST poll     ── inline !command handling (no bot needed)
```

All surfaces are isolated: an exception inside one surface is caught, logged at
WARNING, and never propagates into the orchestrator run loop.

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
WARNING notifications.bus: surface <DiscordDashboard ...> raised on event 'subtask_done' — suppressed
```

### Anti-patterns
- Do **not** make `NotificationBus` a module-level singleton imported at run start.
  Instantiate one per run so surfaces can be re-registered cleanly on restart.
- Do **not** `bus.emit()` inside a surface's own `handle()` — recursive emission
  is not guarded.

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
from notifications.entry import makeEntry, validate, VALID_KINDS

# Create an entry
entry = makeEntry("replan", "added 2 subtasks after verifier failure")

# Validate an arbitrary dict
errors = validate(entry)   # [] means valid
if errors:
    print(errors)

# Write to task state
state.data.setdefault("notifications", []).append(entry)
state.save()
```

### Validation errors returned by `validate()`

- `"missing required key: 'at'"` — key absent
- `"'at' is not valid ISO-8601: ..."` — unparseable timestamp
- `"'kind' must be a non-empty string"` — empty or non-string kind
- `"'detail' must be a str, got ..."` — wrong type

---

## Discord live dashboard (`notifications/dashboard.py`)

### Behaviour
One embed is created at run start and **PATCH-edited in place** on every step
boundary — it never spams new messages.  It is pinned to the channel so it
floats at the top.

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
| Current subtask | `st-NNN title (attempt N)` |
| Working dir | `meta.work_dir` |
| Last verify | `✅/❌ st-NNN — <cmd or expect>` |
| Recent events | Rolling 10-item deque with `HH:MM` timestamps |
| Footer | `task <id[:8]>  · web :<port>  · <control hint>` |

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
If `meta.dashboard_message_id` is set, `start()` tries to edit the existing embed
rather than creating a new one.  This prevents duplicate pinned dashboards when
the orchestrator is restarted mid-run.

- `editMessageResult` returns `"ok"` → reuse the existing message
- Returns `"transient"` (429 / timeout) → reuse the message ID without recreating
- Returns `"not_found"` (genuine 404) → create a fresh embed (once; one-shot guard)

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
`_RATE_LIMITED_UNTIL` is a module-level monotonic deadline.  Any call that hits a
429 response arms the breaker for `retry_after` seconds (capped at 60 s).
All subsequent REST calls (across all surfaces and threads) short-circuit until
the window passes.  A hard 401 latches `_DISABLED = True` for the process lifetime.

---

## Web dashboard (`notifications/webdash.py`)

### Routes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Auto-refreshing HTML status page |
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
next `ControlBus.check()` call inside the run loop (step 4e or a gate boundary).

### Snapshot TTL cache
The `/api/state` handler caches the full `TaskState` snapshot for 1 second
(monotonic clock).  Under rapid browser refresh or concurrent polling this avoids
repeated JSON-parse + disk reads.  Different `task_id` values always miss the
cache.

### Start/stop

The web dashboard is started by the orchestrator as a daemon thread and dies with
the process.  Default port: `127.0.0.1:8787` (set `WEB_DASHBOARD_PORT` in `.env`
to override).

---

## Gateway command bot (`notifications/command_bot.py`)

A `discord.py` gateway bot providing lower-latency `!` command handling than the
inline REST poll.

### Supported commands

| Command | Effect |
|---------|--------|
| `!status` | Post current run status embed |
| `!plan` | Post current subtask list |
| `!log` | Post last 10 notification entries |
| `!abort` | Write `abort` to `ControlBus` |
| `!pause` | Write `pause` to `ControlBus` |
| `!resume` | Write `resume` to `ControlBus` |
| `!approve` | Write `approve` to `ControlBus` (gate decision) |
| `!reject` | Write `reject` to `ControlBus` (gate decision) |
| `!skip <id>` | Write `skip` for the given subtask ID |
| `!add <title>` | Insert a new pending subtask |
| `!retry` | Re-run the current subtask |

### Run (optional)
The orchestrator itself polls the Discord channel between steps so `!commands`
work from `main.py` alone — the gateway bot is optional but provides faster
response.

```
python -m notifications.command_bot
```

### Interactive button actions
`blockedComponents()` renders an action row with **Answer / Skip / Abort** buttons.
Button presses (`custom_id`: `sc_answer`, `sc_skip`, `sc_abort`) are handled by
the gateway bot and mapped to the same `ControlBus` signals as text commands.

---

## Embed size limits

Discord enforces hard limits.  `_clampEmbed()` in `discord_bot.py` enforces them
before every send or edit so a single oversized field never drops the whole embed.

| Limit | Value |
|-------|-------|
| `description` | 4 096 chars |
| Field `name` | 256 chars |
| Field `value` | 1 024 chars |
| Total embed char count | 6 000 |
| Fields per embed | 25 |

The clamp strategy: clamp each field individually first, then shrink the **largest**
field value iteratively until the total is ≤ 6 000.

---

## Conventions

- `ALL_CAPS` — module constants (`VALID_KINDS`, `REQUIRED_KEYS`)
- `snake_case` — variables and parameters
- `camelCase` — functions (`makeEntry`, `progressBar`, `effortBar`)
- `pathlib.Path` everywhere — never `os.path`
- All notification calls are best-effort — they must never halt the run loop
- Secrets (`DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`, etc.) live in `.env` only
