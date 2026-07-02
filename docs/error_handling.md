# 9TO5 — Error Handling Reference

> **Scope:** The `error_handling` module (canonical) and its re-export
> `enhanced_error_handling`.  Covers `retryTask`, `RetryExhausted`, logging
> conventions, and integration examples for the orchestrator loop.

---

## Overview

9TO5 uses a **retry-before-alert** pattern for all fallible operations inside
the orchestrator.  The `retryTask` function wraps any callable, retries it up
to `MAX_RETRIES` times with exponential-friendly sleep between attempts, emits
structured log records at every stage, and either raises `RetryExhausted` or
calls an `on_alert` callback when all attempts are exhausted.

Key invariant: **sleep never fires after the final attempt**.  This avoids
unnecessary wall-clock latency before the alert fires.

---

## Import paths

```python
# Canonical module
from error_handling import retryTask, MAX_RETRIES, RETRY_DELAY_SECONDS, RetryExhausted

# Deliverable alias — re-exports the canonical module identically
from enhanced_error_handling import retryTask
```

Both import paths expose the same objects; the alias exists to satisfy the
deliverable spec name without duplicating implementation.

---

## Constants

| Name | Value | Description |
|------|-------|-------------|
| `MAX_RETRIES` | `3` | Default retry ceiling (attempts before alert) |
| `RETRY_DELAY_SECONDS` | `1.0` | Initial sleep between attempts (seconds) |

Override per call via the `max_retries` and `delay` keyword arguments.

---

## `retryTask`

```python
def retryTask(
    fn: Callable,
    *,
    args: tuple = (),
    kwargs: dict | None = None,
    max_retries: int = MAX_RETRIES,
    delay: float = RETRY_DELAY_SECONDS,
    on_alert: Callable[[str, int], None] | None = None,
) -> dict[str, Any]: ...
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fn` | `Callable` | — | Function to call |
| `args` | `tuple` | `()` | Positional arguments for `fn` |
| `kwargs` | `dict \| None` | `None` | Keyword arguments for `fn` |
| `max_retries` | `int` | `MAX_RETRIES` | Maximum attempts before exhaustion |
| `delay` | `float` | `RETRY_DELAY_SECONDS` | Seconds to sleep *between* attempts |
| `on_alert` | `Callable[[str, int], None] \| None` | `None` | Alert callback `(error_msg, attempts)`; if `None`, raises `RetryExhausted` instead |

### Return value

| Key | Type | Condition |
|-----|------|-----------|
| `ok` | `True` | At least one attempt succeeded |
| `result` | any | Return value of `fn` (success path) |
| `attempts` | `int` | Number of attempts made |
| `ok` | `False` | All attempts failed and `on_alert` was provided |
| `error` | `str` | Last exception as `"ExcType: message"` (failure path) |

### Raises

`RetryExhausted` — when `on_alert` is `None` and all `max_retries` attempts fail.

---

## Examples

### Basic usage — raises on exhaustion

```python
from error_handling import retryTask, RetryExhausted

try:
    result = retryTask(fetch_from_ollama, args=(prompt,))
    # result == {"ok": True, "result": <response>, "attempts": 1}
    response = result["result"]
except RetryExhausted as exc:
    LOG.error("fetch failed after all retries: %s", exc)
```

### With keyword arguments

```python
result = retryTask(
    run_verification,
    kwargs={"subtask_id": "st-003", "work_dir": work_dir},
    max_retries=3,
    delay=2.0,
)
if result["ok"]:
    verify_output = result["result"]
```

### With an alert callback — no exception raised

```python
from error_handling import retryTask
from notifications.bus import NotificationBus

bus: NotificationBus = ...

def on_alert(error_msg: str, attempts: int) -> None:
    bus.emit("subtask_failed", {
        "subtask_id": current_subtask_id,
        "error": error_msg,
        "attempts": attempts,
    })

result = retryTask(
    executor.run,
    args=(subtask,),
    max_retries=3,
    delay=1.0,
    on_alert=on_alert,
)

if not result["ok"]:
    LOG.warning("executor exhausted retries: %s", result["error"])
    # on_alert has already been called; continue to next subtask
```

### Recovery logging (automatic)

When `fn` fails on attempt 1 but succeeds on attempt 2, `retryTask` logs:

```
WARNING 9to5.error_handling: retryTask: attempt 1/3 failed for fetch_from_ollama — ConnectionError: timed out
INFO    9to5.error_handling: retryTask: succeeded on attempt 2/3 for fetch_from_ollama
```

---

## Sleep-after-last-attempt guard

Sleep fires **only between attempts**, never after the final one.  The explicit
guard avoids introducing unnecessary latency before the alert fires:

```python
# Inside retryTask — simplified
for attempt in range(1, max_retries + 1):
    try:
        result = fn(*args, **kw)
        return {"ok": True, "result": result, "attempts": attempt}
    except Exception as exc:
        last_exc = exc
        LOG.warning("attempt %d/%d failed ...", attempt, max_retries, ...)
        if attempt < max_retries:   # guard: skip sleep on last attempt
            time.sleep(delay)

# alert / raise here — no sleep precedes it
```

---

## Logging behaviour

All log records use the logger `9to5.error_handling`.

| Event | Level | Message pattern |
|-------|-------|-----------------|
| Attempt failed | `WARNING` | `retryTask: attempt N/M failed for <fn> — ExcType: msg` |
| Recovered on later attempt | `INFO` | `retryTask: succeeded on attempt N/M for <fn>` |
| All attempts exhausted | `CRITICAL` | `retryTask: all M attempts exhausted for <fn> — last error: ...` |

To capture output in tests:

```python
import logging
logging.getLogger("9to5.error_handling").setLevel(logging.DEBUG)
```

To suppress in unrelated test suites:

```python
logging.getLogger("9to5.error_handling").disabled = True
```

---

## `RetryExhausted`

```python
class RetryExhausted(RuntimeError): ...
```

Raised by `retryTask` when `on_alert` is `None` and all attempts are exhausted.
The message is `"ExcType: last_exception_message"`.

```python
from error_handling import RetryExhausted

try:
    retryTask(risky_fn)
except RetryExhausted as exc:
    # exc.args[0] == "ValueError: something went wrong"
    alert_human(str(exc))
```

---

## Integration with the orchestrator loop

`retryTask` is the standard wrapper for any step that may fail transiently
inside the orchestrator.  Pair it with `NotificationBus.emit` so that
exhaustion events propagate to Discord and the web dashboard:

```python
from error_handling import retryTask
from agents.orchestration_pipeline import StepResult

def on_alert(error_msg: str, attempts: int) -> None:
    bus.emit("subtask_failed", {
        "subtask_id": subtask["subtask_id"],
        "verify_result": error_msg,
        "attempts": attempts,
    })
    state.data["subtasks"][idx]["status"] = "failed"
    state.save()

result = retryTask(
    verifier.runVerification,
    kwargs={"verify": subtask.get("verify"), "work_dir": work_dir, "executor_result": exec_out},
    max_retries=MAX_RETRIES,
    on_alert=on_alert,
)

step = StepResult(
    step="verify",
    ok=result["ok"],
    payload=result.get("result", {}),
    error=result.get("error"),
)
```

---

## Test suite

```bash
# Run all error-handling suites in one shot (recommended)
python run_all_tests.py -v

# Run the acceptance target directly with pytest (pytest ONLY -- running a test file as a
# bare script bypasses the conftest sandbox that blanks the live .env Discord/Ollama creds)
python -m pytest tests/test_error_handling.py -v

# Hardening and simulator suites
python -m pytest tests/test_error_handling_hardening.py -v
python -m pytest tests/test_sim_error_handling.py -v
```

`run_all_tests.py` at the repo root collects all three suites above and
exits with the aggregate pytest return code.  All paths inside it are
resolved via `pathlib.Path` so Windows and POSIX separators are handled
identically by the OS.

---

## Conventions

- `ALL_CAPS` — module constants (`MAX_RETRIES`, `RETRY_DELAY_SECONDS`)
- `snake_case` — variables and parameters
- `camelCase` — functions (`retryTask`)
- stdlib only — no third-party dependencies introduced
- `on_alert` must be side-effect-safe; it must not raise (any exception from it
  would propagate out of `retryTask` uncaught)
