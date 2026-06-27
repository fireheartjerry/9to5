# Retry Policy

## Overview

`retry_policy.py` defines `RetryPolicy`, a structured configuration object that wraps `error_handling.retryTask` with a clean, composable API.

## Module map

| Symbol | Type | Description |
|--------|------|-------------|
| `RetryPolicy` | dataclass | Configuration object; `.execute(fn, *, args, kwargs)` |
| `RetryPolicy.with_alert(fn)` | method | Returns a new policy with `on_alert` set |
| `RetryPolicy.with_retries(n)` | method | Returns a new policy with a different retry ceiling |

## Behaviour

1. Attempts `fn(*args, **kwargs)` up to `max_retries` times.
2. Sleeps `delay` seconds **between** attempts only (never after the final attempt).
3. On exhaustion with `on_alert` set: calls `on_alert(error_msg, attempt_count)` and returns `{"ok": False, ...}`.
4. On exhaustion with no `on_alert`: raises `error_handling.RetryExhausted`.

## Usage

```python
from retry_policy import RetryPolicy

# Basic — raises RetryExhausted after 3 failures
policy = RetryPolicy(max_retries=3, delay=1.0)
result = policy.execute(my_fn, args=(arg1,), kwargs={"k": "v"})
# {"ok": True, "result": ..., "attempts": n, "policy": policy}

# With alert callback — returns {"ok": False} instead of raising
policy = RetryPolicy(max_retries=3, on_alert=send_alert)
result = policy.execute(risky_fn)

# Composition — derive without mutating the base
base = RetryPolicy(max_retries=5, delay=2.0)
prod_policy = base.with_alert(pagerduty_alert)
test_policy = base.with_retries(1)
```

## Result dict

| Key | Present when | Value |
|-----|-------------|-------|
| `ok` | always | `True` on success, `False` on exhaustion with alert |
| `result` | `ok=True` | Return value of `fn` |
| `error` | `ok=False` | `"ExcType: message"` string |
| `attempts` | always | Number of attempts made |
| `policy` | always | The `RetryPolicy` instance used |

## Constants (from `error_handling`)

- `MAX_RETRIES = 3` — default retry ceiling
- `RETRY_DELAY_SECONDS = 1.0` — default inter-attempt sleep

## Tests

```
python C:/9to5/tests/test_retry_policy.py
```

18 tests covering defaults, success paths, exhaustion, sleep behaviour, and composition.

## Related files

- `error_handling.py` — `retryTask`, `RetryExhausted`, `MAX_RETRIES`, `RETRY_DELAY_SECONDS`
- `tests/test_retry_policy.py` — acceptance test suite
- `tests/test_error_handling.py` — lower-level `retryTask` tests
