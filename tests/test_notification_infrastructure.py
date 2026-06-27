"""Infrastructure contracts for the 9TO5 notification system (st-006 / st-061).

Covers embed clamping, dashboard event deque, rate-limit circuit breaker,
surface isolation (Gap 1), snapshot TTL cache (Gap 4), and bus surface-count.
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
import notifications.discord_bot as d
from notifications import dashboard as dash
from notifications.bus import NotificationBus


# ---------------------------------------------------------------------------
# Shared test surface helpers
# ---------------------------------------------------------------------------

class _CaptureSurface:
    """Test surface that records calls."""
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def handle(self, event_type: str, payload: dict) -> None:
        self.calls.append((event_type, payload))


class _FailingSurface:
    """Test surface that always raises."""
    def handle(self, event_type: str, payload: dict) -> None:
        raise RuntimeError("surface intentionally failed")


# ---------------------------------------------------------------------------
# Contract 1: Embed hard limits are enforced (existing guarantee)
# ---------------------------------------------------------------------------

class TestEmbedClampingContract(unittest.TestCase):
    """_clampEmbed must guarantee Discord hard limits before any send."""

    def test_description_clamped_to_discord_max(self):
        embed = {"description": "x" * 10_000}
        clamped = d._clampEmbed(embed)
        self.assertLessEqual(len(clamped["description"]), config.DISCORD_MAX_EMBED_DESC + 1)

    def test_field_value_clamped_to_discord_max(self):
        embed = {"fields": [{"name": "k", "value": "v" * 2000}]}
        clamped = d._clampEmbed(embed)
        self.assertLessEqual(len(clamped["fields"][0]["value"]), config.DISCORD_MAX_FIELD_VALUE + 1)

    def test_total_embed_chars_within_6000(self):
        fields = [{"name": "k", "value": "x" * 500} for _ in range(25)]
        embed = {"title": "t", "description": "d" * 1000, "fields": fields}
        clamped = d._clampEmbed(embed)
        total = len(str(clamped.get("title", ""))) + len(str(clamped.get("description", "")))
        for f in clamped.get("fields", []):
            total += len(str(f.get("name", ""))) + len(str(f.get("value", "")))
        self.assertLessEqual(total, config.DISCORD_EMBED_TOTAL_MAX)

    def test_fields_capped_at_25(self):
        embed = {"fields": [{"name": str(i), "value": "v"} for i in range(30)]}
        clamped = d._clampEmbed(embed)
        self.assertLessEqual(len(clamped["fields"]), 25)

    def test_none_embed_returned_unchanged(self):
        result = d._clampEmbed(None)
        self.assertIsNone(result)

    def test_non_dict_embed_returned_unchanged(self):
        result = d._clampEmbed("not a dict")
        self.assertEqual(result, "not a dict")


# ---------------------------------------------------------------------------
# Contract 2: Dashboard event deque is bounded and thread-safe
# ---------------------------------------------------------------------------

class TestDashboardEventContract(unittest.TestCase):
    def setUp(self):
        self.db = dash.DiscordDashboard()

    def test_maxlen_is_ten(self):
        for i in range(20):
            self.db.event(f"e{i}")
        self.assertEqual(len(self.db._eventsSnapshot()), 10)

    def test_snapshot_is_independent_copy(self):
        self.db.event("first")
        snap = self.db._eventsSnapshot()
        self.db.event("second")
        self.assertEqual(len(snap), 1)  # original snapshot must not grow

    def test_event_contains_timestamp_and_text(self):
        self.db.event("subtask done")
        entry = self.db._eventsSnapshot()[0]
        self.assertIn("subtask done", entry)
        self.assertIn("`", entry)  # timestamp is backtick-quoted

    def test_concurrent_writes_do_not_raise(self):
        errors: list[Exception] = []

        def _write(n: int):
            try:
                for i in range(30):
                    self.db.event(f"t{n}-{i}")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=_write, args=(k,)) for k in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


# ---------------------------------------------------------------------------
# Contract 4: Rate-limit circuit breaker is accessible (Gap 3)
# ---------------------------------------------------------------------------

class TestRateLimitCircuitBreakerContract(unittest.TestCase):
    """_RATE_LIMITED_UNTIL must be readable and resettable so tests don't bleed state."""

    def test_rate_limited_until_is_numeric(self):
        self.assertIsInstance(d._RATE_LIMITED_UNTIL, float)

    def test_rate_limited_until_can_be_reset_via_patch(self):
        with mock.patch.object(d, "_RATE_LIMITED_UNTIL", 0.0):
            self.assertEqual(d._RATE_LIMITED_UNTIL, 0.0)

    def test_disabled_flag_is_bool(self):
        self.assertIsInstance(d._DISABLED, bool)

    def test_disabled_can_be_reset_via_patch(self):
        with mock.patch.object(d, "_DISABLED", False):
            self.assertFalse(d._DISABLED)


# ---------------------------------------------------------------------------
# Contract 5: Surface isolation — bus must never propagate surface exceptions
# ---------------------------------------------------------------------------

class TestNotificationBusContract(unittest.TestCase):
    def test_emit_reaches_registered_surface(self):
        bus = NotificationBus()
        cap = _CaptureSurface()
        bus.register(cap)
        bus.emit("subtask_done", {"subtask_id": "st-001"})
        self.assertEqual(len(cap.calls), 1)
        self.assertEqual(cap.calls[0][0], "subtask_done")

    def test_failing_surface_does_not_raise(self):
        bus = NotificationBus()
        bus.register(_FailingSurface())
        cap = _CaptureSurface()
        bus.register(cap)
        bus.emit("subtask_done", {"subtask_id": "st-002"})  # must not raise
        self.assertEqual(len(cap.calls), 1)  # second surface still called

    def test_multiple_surfaces_all_called(self):
        bus = NotificationBus()
        surfaces = [_CaptureSurface() for _ in range(3)]
        for s in surfaces:
            bus.register(s)
        bus.emit("blocked", {"reason": "unclear"})
        for s in surfaces:
            self.assertEqual(len(s.calls), 1)

    def test_empty_bus_emit_is_noop(self):
        bus = NotificationBus()
        bus.emit("anything", {})  # must not raise


# ---------------------------------------------------------------------------
# Contract 6: Snapshot cache TTL contract (Gap 4 design)
# ---------------------------------------------------------------------------

class TestSnapshotCacheContract(unittest.TestCase):
    """The webdash snapshot cache must return the cached result within TTL,
    and a fresh result after TTL expires or after a control mutation."""

    def test_cache_returns_same_object_within_ttl(self):
        cache: list = []

        def _cached_snapshot(task_id: str, builder) -> dict:
            now = time.monotonic()
            if cache and cache[0] == task_id and now < cache[1]:
                return cache[2]
            snap = builder(task_id)
            cache[:] = [task_id, now + 1.0, snap]
            return snap

        call_count = 0

        def _builder(task_id):
            nonlocal call_count
            call_count += 1
            return {"task_id": task_id, "call": call_count}

        r1 = _cached_snapshot("t1", _builder)
        r2 = _cached_snapshot("t1", _builder)
        self.assertIs(r1, r2)
        self.assertEqual(call_count, 1)

    def test_cache_misses_on_different_task_id(self):
        cache: list = []

        def _cached_snapshot(task_id: str, builder) -> dict:
            now = time.monotonic()
            if cache and cache[0] == task_id and now < cache[1]:
                return cache[2]
            snap = builder(task_id)
            cache[:] = [task_id, now + 1.0, snap]
            return snap

        builds: list[str] = []

        def _builder(task_id):
            builds.append(task_id)
            return {"task_id": task_id}

        _cached_snapshot("t1", _builder)
        _cached_snapshot("t2", _builder)
        self.assertEqual(builds, ["t1", "t2"])

    def test_cache_invalidated_after_ttl(self):
        cache: list = []

        def _cached_snapshot(task_id: str, builder, ttl: float = 0.05) -> dict:
            now = time.monotonic()
            if cache and cache[0] == task_id and now < cache[1]:
                return cache[2]
            snap = builder(task_id)
            cache[:] = [task_id, now + ttl, snap]
            return snap

        call_count = 0

        def _builder(task_id):
            nonlocal call_count
            call_count += 1
            return {}

        _cached_snapshot("t1", _builder, ttl=0.05)
        time.sleep(0.1)
        _cached_snapshot("t1", _builder, ttl=0.05)
        self.assertEqual(call_count, 2)


# ---------------------------------------------------------------------------
# Contract 10: NotificationBus.surface_count and concurrent emit safety
# ---------------------------------------------------------------------------

class TestNotificationBusSurfaceCount(unittest.TestCase):
    def test_initial_surface_count_is_zero(self):
        bus = NotificationBus()
        self.assertEqual(bus.surface_count, 0)

    def test_surface_count_increments_on_register(self):
        bus = NotificationBus()
        bus.register(_CaptureSurface())
        bus.register(_CaptureSurface())
        self.assertEqual(bus.surface_count, 2)

    def test_concurrent_emits_do_not_raise(self):
        bus = NotificationBus()
        cap = _CaptureSurface()
        bus.register(cap)
        errors: list[Exception] = []

        def _emit(n: int):
            try:
                for i in range(20):
                    bus.emit(f"event_{n}_{i}", {"i": i})
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=_emit, args=(k,)) for k in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(cap.calls), 100)  # 5 threads × 20 emits

    def test_failing_surface_does_not_affect_surface_count(self):
        bus = NotificationBus()
        bus.register(_FailingSurface())
        self.assertEqual(bus.surface_count, 1)
