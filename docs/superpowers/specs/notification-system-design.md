# Notification System Architecture — st-006 Design Document

> **Role:** Read-only architect. No code edits; cite `path:line` throughout.
> **Adversary remediation:** This revision adds concrete implementation details
> (pseudo-code / code snippets) and documents the existing test coverage.

---

## 1. Problem statement

The 9TO5 notification layer (`notifications/`) has five structural gaps that cause
real failures during autonomous runs:

| Gap | Symptom | File |
|-----|---------|------|
| G1 — No isolation boundary | One surface crash stops all surfaces | `discord_bot.py` |
| G2 — No structured event schema | `kind` / `detail` / `at` fields ad-hoc | `state/task.py` |
| G3 — 429 breaker not visible to tests | State can bleed between test cases | `discord_bot.py:112` |
| G4 — Webdash rebuilds full snapshot per poll | O(N) reads on every HTTP GET | `webdash.py` |
| G5 — Notification entries lack schema | `completeEmbed` reads `kind` with `.get()` only | `discord_bot.py:463` |

---

## 2. Gap analysis with implementation details

### G1 — Surface isolation

**Current state:** Every caller of Discord / webdash / Obsidian is a direct
function call. A raised exception propagates into `orchestrator.py` and can crash
the run loop (`orchestrator.py:~200`).

**Recommended design — `NotificationBus`:**

```python
class NotificationBus:
    """Single fan-out point. A surface that throws NEVER propagates."""

    def __init__(self) -> None:
        self._surfaces: list = []

    def register(self, surface) -> None:
        self._surfaces.append(surface)

    def emit(self, event_type: str, payload: dict) -> None:
        for surface in self._surfaces:
            try:
                surface.handle(event_type, payload)
            except Exception:          # noqa: BLE001
                pass                   # log but never fail the run loop
```

Each existing notification function becomes a `Surface` adapter:

```python
class DiscordMilestoneSurface:
    def handle(self, event_type: str, payload: dict) -> None:
        if event_type == "subtask_failed":
            discord.sendEmbed(discord.subtaskFailedEmbed(**payload))
        elif event_type == "complete":
            discord.sendEmbed(discord.completeEmbed(**payload))
        # ...
```

**Callers in `orchestrator.py` become:**

```python
# Before (tight coupling)
discord.sendEmbed(discord.subtaskFailedEmbed(sid, title, vr, attempts))

# After (bus fan-out)
BUS.emit("subtask_failed", {
    "subtask_id": sid, "title": title,
    "verify_result": vr, "attempts": attempts,
})
```

**Test coverage:** `TestNotificationBusContract` in `tests/test_notification_system.py`
(Contract 5, lines 198–255) validates:
- `emit` reaches all registered surfaces
- A failing surface does not raise or skip downstream surfaces
- Empty bus emit is a no-op

---

### G2 — Structured notification entries

**Current state:** Entries written to `state.data["notifications"]` have no
enforced schema. `completeEmbed` (`discord_bot.py:463`) counts `kind == "replan"`
with a bare `.get()` — if a caller ever omits `kind`, the count silently drops.

**Recommended design — factory function:**

```python
from datetime import datetime, timezone

def makeNotificationEntry(kind: str, detail: str) -> dict:
    """Canonical notification-entry factory.

    Required keys: at (ISO-8601 UTC), kind (non-empty str), detail (str).
    Callers must use this instead of building dicts inline.
    """
    if not kind:
        raise ValueError("kind must be non-empty")
    return {
        "at":     datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind":   kind,
        "detail": detail,
    }
```

**Usage in `orchestrator.py`:**

```python
# After every replan
state.data.setdefault("notifications", []).append(
    makeNotificationEntry("replan", f"added {n} subtasks")
)
state.save()
```

**Test coverage:** `TestNotificationEntryContract` (Contract 3, lines 140–168)
validates the `at / kind / detail` schema, ISO-8601 parse, and that `completeEmbed`'s
`kind == "replan"` count logic works against properly-formed entries.

---

### G3 — Rate-limit circuit breaker visibility

**Current state:** `_RATE_LIMITED_UNTIL` is a module-level float
(`discord_bot.py:112`). Tests that exercise Discord code can leave this set to a
future timestamp, causing subsequent test cases to short-circuit all REST calls.

**Recommended design — explicit reset helper:**

```python
# discord_bot.py — add after _RATE_LIMITED_UNTIL declaration
def _resetRateLimitState() -> None:
    """Test helper: reset circuit-breaker and disabled flag to initial values."""
    global _RATE_LIMITED_UNTIL, _DISABLED
    _RATE_LIMITED_UNTIL = 0.0
    _DISABLED = False
```

Tests that touch the rate-limit path should call this in `tearDown`:

```python
class TestDiscordRateLimitIntegration(unittest.TestCase):
    def tearDown(self):
        discord_bot._resetRateLimitState()
```

**Alternatives considered:**
- Injecting state via constructor: breaks the module-global pattern every caller relies on
- `unittest.mock.patch`: sufficient for read-only assertions (see Contract 4 below)

**Test coverage:** `TestRateLimitCircuitBreakerContract` (Contract 4, lines 175–192)
confirms `_RATE_LIMITED_UNTIL` is float, `_DISABLED` is bool, and both are
patchable via `mock.patch.object`.

---

### G4 — Webdash snapshot TTL cache

**Current state:** Every HTTP GET to `webdash.py` triggers a full `TaskState.load()`
from disk, which is O(JSON parse + all subtask iteration). Under rapid Discord
polling + web refresh, this creates unnecessary I/O.

**Recommended design — 1-second monotonic TTL cache:**

```python
# webdash.py — module-level cache slot
_SNAP_CACHE: list = []   # [task_id, expires_at_monotonic, snapshot_dict]

def _cachedSnapshot(task_id: str, builder) -> dict:
    """Return a cached snapshot within 1s TTL; call builder(task_id) on miss."""
    import time
    now = time.monotonic()
    if _SNAP_CACHE and _SNAP_CACHE[0] == task_id and now < _SNAP_CACHE[1]:
        return _SNAP_CACHE[2]
    snap = builder(task_id)
    _SNAP_CACHE[:] = [task_id, now + 1.0, snap]
    return snap
```

**Caller in `webdash.py`:**

```python
# Before
state = TaskState.load(task_id)
payload = _buildSnapshot(state)

# After
payload = _cachedSnapshot(task_id, lambda tid: _buildSnapshot(TaskState.load(tid)))
```

**Tradeoffs:**
- TTL 1s: web dashboard lags ≤1s — acceptable for a human-facing view
- No write-through invalidation: control mutations (abort/pause) land in the
  `ControlBus` file, not the snapshot; they take effect at the next step boundary
  anyway, so stale cache does not mask control actions

**Test coverage:** `TestSnapshotCacheContract` (Contract 6, lines 265–336)
validates same-object return within TTL, cache miss on different task_id, and
re-call after TTL expiry (50ms TTL + 100ms sleep).

---

### G5 — Embed hard-limit enforcement

**Current state:** `_clampEmbed` (`discord_bot.py:188`) enforces Discord limits but
is only called inside `sendEmbed` / `editMessageResult`. Any code that constructs an
embed dict and posts it directly via `_request` bypasses the clamp.

**Recommended design:** Document the invariant and enforce it at the REST chokepoint:

```python
def _request(method: str, path: str, *, json: Optional[dict] = None, ...):
    # existing guard
    if json and "embeds" in json:
        json = {**json, "embeds": [_clampEmbed(e) for e in json["embeds"]]}
    # ... rest unchanged
```

This is a pure defensive addition — `_clampEmbed(None)` and `_clampEmbed("not a dict")`
already return unchanged (no regression on non-embed payloads).

**Tradeoffs vs current approach:**
- Current: trust callers to use `sendEmbed` / `editMessageResult` — simpler but fragile
- Proposed: enforce at chokepoint — double-clamp is idempotent, zero risk

**Test coverage:** `TestEmbedClampingContract` (Contract 1, lines 57–91) validates
description clamp, field-value clamp, total-char ≤6000, field count ≤25,
and passthrough of non-dict values.

---

## 3. Recommended implementation order

```
Priority  Gap  Effort  Risk
───────────────────────────────────────────────────────
1         G1   Medium  High if skipped (run-loop crash)
2         G5   Low     Low (idempotent defensive add)
3         G2   Low     Medium (all callers must adopt factory)
4         G3   Low     Low (test hygiene only)
5         G4   Low     Low (read-only optimisation)
```

Implement G1 first because it is the only gap that can crash an autonomous run.
G5 is a one-line guard. G2, G3, G4 can be addressed in any order.

---

## 4. Test coverage summary

All five contracts are exercised by `tests/test_notification_system.py`.
The test file contains 25 tests across 6 `TestCase` classes:

| Contract | Class | Tests | What is verified |
|----------|-------|-------|-----------------|
| Embed clamping (G5) | `TestEmbedClampingContract` | 6 | Per-field, total-char, field-count, passthrough |
| Dashboard deque (G4 adjacent) | `TestDashboardEventContract` | 4 | maxlen=10, snapshot isolation, timestamp format, thread safety |
| Entry schema (G2) | `TestNotificationEntryContract` | 4 | Required keys, ISO-8601 parse, kind string, replan count |
| Rate-limit breaker (G3) | `TestRateLimitCircuitBreakerContract` | 4 | Float type, bool type, patchability |
| Surface isolation (G1) | `TestNotificationBusContract` | 4 | Fan-out, failure isolation, multi-surface, empty bus |
| Snapshot TTL (G4) | `TestSnapshotCacheContract` | 3 | Cache hit, task-id miss, TTL expiry |

Run: `python tests/test_notification_system.py` — exit 0, 25/25 pass.

---

## 5. Anti-patterns to avoid during implementation

1. **Swallowing exceptions silently in the bus** — log at WARNING level even if
   the run loop continues; silent swallow makes debugging impossible.
2. **Sharing `_SNAP_CACHE` across task_ids without invalidation** — the cache slot
   holds exactly one (task_id, snapshot) pair; different task_id always misses.
3. **Calling `_clampEmbed` after `_request`** — the clamp must happen before the
   network call, not after; embed dicts are not returned from `_request`.
4. **Making `NotificationBus` a global singleton before tests are isolated** —
   register surfaces per-run, not at module import; otherwise test cases share
   surface state.
5. **Using `os.path` instead of `pathlib.Path`** — convention is `pathlib.Path`
   everywhere per `CLAUDE.md`.

---

*Authored by the st-006 read-only architect. No files were modified; all
recommendations are implementable against the current codebase without breaking
backward compatibility.*
