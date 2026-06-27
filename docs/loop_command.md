# `/loop` command — usage guide

`/loop` is a **CC slash command** (Claude Code native) handled entirely by the
Claude Code CLI process.  It is **not** a 9TO5 Python API call, not a Discord
command, and not something you can invoke from a subprocess.

---

## What `/loop` does

Repeats a prompt or slash command on a recurring schedule.  Two modes:

| Mode | When to use |
|------|-------------|
| **Fixed interval** — `/loop 5m /foo` | Poll external state that changes on a known cadence (CI runs, deploy queue, status page) |
| **Self-paced** — `/loop /foo` | Let the model decide when to fire next via `ScheduleWakeup`; used for autonomous work with variable pacing |

---

## Syntax

```
/loop [interval] <prompt-or-slash-command>
```

- `interval` is optional.  Supported units: `s` (seconds), `m` (minutes), `h` (hours).
- When `interval` is omitted the model self-paces: it calls `ScheduleWakeup` at
  the end of each turn to schedule the next wake-up based on what it's watching.
- `<prompt-or-slash-command>` is the task to run each iteration.  It can be
  free-form text or another slash command (e.g. `/babysit-prs`).

---

## Examples

**Fixed intervals — common cadences:**

```
# Every 15 minutes — poll a deploy queue or staging health endpoint
/loop 15m check whether the staging deployment finished

# Every 30 minutes — moderate-cadence status sweep
/loop 30m summarise open review comments on feat/frontier-discord-ui

# Hourly — CI summary posted to Discord
/loop 1h summarise overnight CI

# Every 5 minutes — active PR watch (cache stays warm, ~270 s sweet spot)
/loop 5m /babysit-prs

# Free-form prompt, fixed cadence
/loop 10m check the deploy
```

**Self-paced (no interval) — model decides when to fire next:**

```
#self-paced — Claude calls ScheduleWakeup with a delay it calculates from context
/loop /check-deploy
```

---

## Self-paced mode

When no interval is given, Claude calls `ScheduleWakeup` at the end of each turn
with a `delaySeconds` chosen to match the task's natural cadence:

- **Under 5 min (60–270 s):** prompt cache stays warm; right for active polling.
- **5 min–1 h (300–3600 s):** cache miss on wake-up; right for slow-changing state.
- **Default idle:** 1200–1800 s (20–30 min) when nothing specific needs watching.

Do not pick 300 s — it is the worst of both worlds (cache miss without the long
wait amortising it).

---

## When to use

- Polling external state Claude cannot receive push notifications for (CI, deploys,
  remote queues).
- Autonomous watch loops: "keep watching PRs and comment when tests fail".
- Recurring summaries: "every hour, post a CI summary to Discord".

---

## When NOT to use

- **One-off tasks** — just run the prompt directly.
- **Programmatic retry inside 9TO5** — use `retryTask` from `error_handling.py`
  instead; `/loop` is a CLI-level feature, not a Python API.
- **Hard real-time requirements** — `/loop` fires approximately on schedule;
  it is not a precise timer.

---

## Anti-patterns

| Wrong | Right |
|-------|-------|
| `subprocess.run(["claude", "/loop", ...])` | Type `/loop` directly in Claude Code |
| Calling `/loop` from a 9TO5 orchestrator Python function | Use `retryTask` for programmatic retry |
| Setting interval to exactly `300` s | Use 270 s (cache-warm) or 1200 s+ (cache-miss amortised) |
| Swallowing exceptions in the loop body | Re-raise or emit `subtask_failed` so the orchestrator tracks failures |

---

## Stopping a loop

Press **Ctrl-C** in the Claude Code terminal, or close the session.  The loop
does not persist across sessions unless you re-invoke `/loop`.

---

## Error handling inside a loop body

Loop iterations run as standard Claude Code turns.  Transient errors do not
stop the loop — the next interval fires regardless.  Surface hard failures
explicitly:

```python
try:
    result = execute_step()
except Exception as exc:
    bus.emit("subtask_failed", {"error": str(exc), "attempts": 1})
    raise   # non-zero exit signals failure to CC
```

For retryable operations, use `retryTask` before the failure bubbles up:

```python
from error_handling import retryTask, MAX_RETRIES, RetryExhausted

result = retryTask(fetch_data, args=(url,), max_retries=MAX_RETRIES)
```

---

## Relationship to 9TO5 orchestration

`/loop` is a **CC-layer** feature.  9TO5's orchestrator has its own retry and
scheduling mechanisms:

| Need | Use |
|------|-----|
| Retry a failing subtask | `retryTask` / `MAX_SUBTASK_ATTEMPTS` |
| Schedule a recurring 9TO5 run | Cron + `python main.py` |
| Watch an external resource from Claude Code | `/loop` |
| Self-paced autonomous Claude Code monitoring | `/loop` (no interval) |

See also: `docs/notification_system.md § /loop command — correct usage and best practices`.
