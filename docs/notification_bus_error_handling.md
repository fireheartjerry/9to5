# NotificationBus — Error Handling Reference

> **Scope:** `notifications/bus.py` only — the fan-out isolation contract,
> suppression semantics, logging behaviour, and guidance for surface authors
> and test writers.  For the full notification system see
> `docs/notification_system.md`.

---

## The isolation contract

`NotificationBus.emit()` takes a snapshot of registered surfaces under the
lock, then iterates outside the lock so that surfaces may themselves call
`bus.register()` without deadlocking.  Every `surface.handle()` call is
wrapped in a `try/except BaseException` block.  A surface that raises for
**any** reason is logged and skipped; the event is delivered to all remaining
surfaces.  The caller (`orchestrator.py`) **never** sees the exception.

```python
# notifications/bus.py — emit() core loop (abridged)
with self._lock:
    snapshot = list(self._surfaces)          # copy under lock, iterate outside

for surface in snapshot:
    try:
        surface.handle(event_type, payload)
    except BaseException:                    # surface errors must never reach callers
        _log.exception(
            "surface %r raised on event %r — suppressed", surface, event_type
        )
```

**Guarantees per `emit()` call:**

| Situation | Result |
|---|---|
| Surface A raises; surfaces B and C remain | B and C still receive the event |
| Surface raises `RuntimeError` | Logged at WARNING with full traceback; caller unaffected |
| Surface raises `KeyboardInterrupt` | **suppressed** per-surface (see below) |
| Surface raises `SystemExit` | **suppressed** per-surface (see below) |
| No surfaces registered | Silent no-op; `emit()` returns immediately |

---

## KeyboardInterrupt and SystemExit inside a surface

`BaseException` (not `Exception`) is caught deliberately.  `Exception` would
let `KeyboardInterrupt` and `SystemExit` propagate; catching `BaseException`
prevents that.

This means `KeyboardInterrupt` and `SystemExit` raised *inside* a surface's
`handle()` method are **suppressed** — they do not reach the caller.  A
surface that calls `sys.exit()` or whose thread receives a SIGINT while inside
`handle()` cannot kill or interrupt the orchestrator run loop.

**Implication for surface authors:** do not assume `KeyboardInterrupt` or
`SystemExit` will propagate out of `handle()` — they are **suppressed** just
like any other exception.  Graceful shutdown signals must flow through
`ControlBus` (write an `abort` or `pause` command to the control file), not
through exceptions raised inside surfaces.

---

## What is NOT suppressed

Only **per-surface** exceptions are swallowed.  Errors raised *before*
`emit()` reaches the surface loop propagate normally to the caller:

- `TypeError` / `AttributeError` from wrong argument types passed to `emit()`
  (e.g. `event_type` is not a `str`, `payload` is not a `dict`)
- Any exception raised inside `emit()` itself before the `for` loop starts
- Lock acquisition errors on `self._lock` (pathological; should never occur)

Errors from `NotificationBus.__init__()` or `register()` are also **NOT
suppressed** and propagate normally.

---

## Logging behaviour

| Condition | Level | Logger | Method | Notes |
|---|---|---|---|---|
| Surface raises `BaseException` | `WARNING` | `notifications.bus` | `exception()` | One record per failing surface per `emit()` call; includes full traceback |
| Successful emission | *(silent)* | — | — | No log output for the happy path |

`exception()` is used (not `warning()`) so the full traceback is embedded in
the log record automatically — no manual `traceback.format_exc()` needed.

To capture bus error output in your own code:

```python
import logging
logging.getLogger("notifications.bus").setLevel(logging.WARNING)
```

To suppress bus log output during a test run (e.g. to keep CI output clean):

```python
logging.getLogger("notifications.bus").disabled = True
```

Re-enable it before any test that asserts on log output (e.g. `assertLogs`).

---

## Expected tracebacks in tests

When tests intentionally raise inside a surface (to verify the isolation
contract), `logging.exception()` writes the full traceback to the log handler.
**This is correct behaviour**, not a test failure.  The test still passes
(`OK`) because the exception never reaches the caller.

Example (expected output, not an error):

```
WARNING:notifications.bus:surface <_RaisingSurface …> raised on event 'replan' — suppressed
Traceback (most recent call last):
  …
ValueError: bad surface
```

Tests that assert on log records use `assertLogs("notifications.bus", level="WARNING")`,
which captures and suppresses the handler — no visible traceback is printed for
those test cases.

---

## surface_count helper

`bus.surface_count` returns the number of currently registered surfaces.
Reading it acquires `self._lock`, so it reflects the count at the instant of
the call (not a cached value).  Use it in tests or health checks to confirm
surfaces were registered before emitting:

```python
assert bus.surface_count == 2, "expected discord + web surfaces"
```

`surface_count` is a `@property`; accessing it as a callable (`bus.surface_count()`)
raises `TypeError`.

---

## Guidance for surface authors

- **Never raise from `handle()` to signal failure.** The exception is
  suppressed; the caller never sees it.  Use an out-of-band mechanism (a
  shared flag, a `ControlBus` write) if a surface needs to communicate a
  fatal condition upstream.
- **Do not rely on `KeyboardInterrupt` or `SystemExit` propagating from
  `handle()`.** They are suppressed by the `BaseException` catch in `emit()`.
  For graceful shutdown, write to `ControlBus` (`abort`/`pause`) instead.
- **Do not call `bus.emit()` inside `handle()`.** `emit()` takes a snapshot
  under `self._lock` and iterates outside it; calling `emit()` recursively
  from within `handle()` will attempt to re-acquire `self._lock`, which is a
  non-reentrant `threading.Lock()` — this deadlocks immediately.
- **Keep `handle()` fast.** `emit()` calls surfaces synchronously in
  registration order.  A slow surface delays all subsequent surfaces for that
  event.

---

## Anti-patterns

| Anti-pattern | Why it breaks |
|---|---|
| Module-level singleton `BUS = NotificationBus()` at import time | Surfaces can't be re-registered cleanly on resilience restart; import-time side effects are hard to test |
| Raising from `handle()` to abort a run | Exception is swallowed by `emit()`; orchestrator run loop never sees it |
| Calling `bus.emit()` inside `handle()` | Acquires the same non-reentrant lock → immediate deadlock; recursive emission is not guarded against |
| Catching `BaseException` inside `handle()` and re-raising `SystemExit` | Still suppressed by the outer `BaseException` catch in `emit()` |
| Storing a reference to `self._surfaces` directly | The internal list is mutated under lock; reading it unsafely is a data race |

---

## ControlBus for shutdown signals

`ControlBus` (`control.py`) is the correct channel for surfaces that need to
signal abort or pause to the orchestrator.  Write a control command from
inside `handle()` instead of raising:

```python
# correct: signal shutdown via ControlBus, not an exception
from control import ControlBus

class MyShutdownSurface:
    def handle(self, event_type: str, payload: dict) -> None:
        if event_type == "fatal_error":
            ControlBus.write_abort(reason="surface detected fatal condition")
        # return normally; raising here is suppressed anyway
```

The orchestrator checks `ControlBus` at every step boundary, so the abort
takes effect at the next safe point — not mid-surface.

---

## Quick reference

```python
from notifications.bus import NotificationBus, NotificationSurface

bus = NotificationBus()
bus.register(my_surface)          # surface must implement handle(event_type, payload)
bus.emit("subtask_done", {...})   # never raises; per-surface errors are suppressed
bus.surface_count                 # int — number of registered surfaces (property, not callable)
```
