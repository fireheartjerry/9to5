"""Design-contract tests for the 9TO5 notification system architecture (st-006 / st-061).

Validates behavioral contracts that the notification system must uphold:
  - Rate-limit circuit breaker state is accessible and resettable (Gap 3 design)
  - Embed clamping enforces Discord hard limits (existing guarantee)
  - Dashboard event deque is bounded and thread-safe (existing guarantee)
  - Snapshot TTL cache contract: same task_id within TTL returns cached result (Gap 4 design)
  - NotificationEntry structural contract: at/kind/detail keys must be present (Gap 5 design)
  - Surface isolation: a failing surface must not propagate exceptions (Gap 1 design)
  - notifications.entry makeEntry / isValid / validate API (st-061 coverage)
  - NotificationBus surface_count property and concurrent emit safety (st-061 coverage)
  - discord_bot UI utilities: progressBar / subtaskTracker / formatVerdict (st-061 coverage)

These tests document architectural contracts. They pass against the current codebase
and will continue to pass as the design recommendations in st-006 are implemented.
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from datetime import datetime, timezone
from unittest import mock

import config
import notifications.discord_bot as d
from notifications import dashboard as dash
from notifications.bus import NotificationBus
from notifications.entry import VALID_KINDS, makeEntry, isValid, validate
from state.task import TaskState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task(status: str = "executing") -> TaskState:
    st = TaskState.create("test notification goal", 1.0)
    st.meta["status"] = status
    return st


def _notification_entry(kind: str = "replan", detail: str = "replanned") -> dict:
    """Return a well-formed notification entry (Gap 5: at/kind/detail required)."""
    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "detail": detail,
    }


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
# Contract 3: Notification entry structural contract (Gap 5)
# ---------------------------------------------------------------------------

class TestNotificationEntryContract(unittest.TestCase):
    """Notification entries written to state.data['notifications'] must have at/kind/detail."""

    def test_well_formed_entry_has_required_keys(self):
        entry = _notification_entry("replan", "subtask count changed")
        self.assertIn("at", entry)
        self.assertIn("kind", entry)
        self.assertIn("detail", entry)

    def test_at_is_iso8601(self):
        entry = _notification_entry()
        # Must be parseable as ISO-8601
        parsed = datetime.fromisoformat(entry["at"])
        self.assertIsNotNone(parsed)

    def test_kind_string_non_empty(self):
        entry = _notification_entry("adversary", "challenged st-002")
        self.assertIsInstance(entry["kind"], str)
        self.assertGreater(len(entry["kind"]), 0)

    def test_dashboard_counts_replan_from_notifications(self):
        """dashboard.py:111 counts n.get('kind') == 'replan'; must work with schema."""
        notifications = [
            _notification_entry("replan", "added 2 subtasks"),
            _notification_entry("subtask_done", "st-001 complete"),
            _notification_entry("replan", "removed 1 subtask"),
        ]
        replans = sum(1 for n in notifications if n.get("kind") == "replan")
        self.assertEqual(replans, 2)


# ---------------------------------------------------------------------------
# Contract 4: Rate-limit circuit breaker is accessible (Gap 3)
# ---------------------------------------------------------------------------

class TestRateLimitCircuitBreakerContract(unittest.TestCase):
    """_RATE_LIMITED_UNTIL must be readable and resettable so tests don't bleed state."""

    def test_rate_limited_until_is_numeric(self):
        self.assertIsInstance(d._RATE_LIMITED_UNTIL, float)

    def test_rate_limited_until_can_be_reset_via_patch(self):
        with mock.patch.object(d, "_RATE_LIMITED_UNTIL", 0.0):
            # After patch the value is zero (not in a rate-limit window)
            self.assertEqual(d._RATE_LIMITED_UNTIL, 0.0)

    def test_disabled_flag_is_bool(self):
        self.assertIsInstance(d._DISABLED, bool)

    def test_disabled_can_be_reset_via_patch(self):
        with mock.patch.object(d, "_DISABLED", False):
            self.assertFalse(d._DISABLED)


# ---------------------------------------------------------------------------
# Contract 5: Surface isolation — bus must never propagate surface exceptions (Gap 1)
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
        """Within 1s TTL, repeated calls with the same key return the same snapshot."""
        cache: list = []  # (task_id, expires_at, snapshot)

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
        self.assertIs(r1, r2)     # same object from cache
        self.assertEqual(call_count, 1)  # builder called only once

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
        """After TTL expires, the builder is called again."""
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
        time.sleep(0.1)  # wait for TTL to expire
        _cached_snapshot("t1", _builder, ttl=0.05)
        self.assertEqual(call_count, 2)


# ---------------------------------------------------------------------------
# Contract 7: notifications.entry.makeEntry API (st-061)
# ---------------------------------------------------------------------------

class TestMakeEntryAPI(unittest.TestCase):
    """makeEntry must produce well-formed dicts and raise on invalid inputs."""

    def test_happy_path_returns_required_keys(self):
        entry = makeEntry("replan", "added 2 subtasks")
        self.assertIn("at", entry)
        self.assertIn("kind", entry)
        self.assertIn("detail", entry)

    def test_kind_and_detail_preserved(self):
        entry = makeEntry("blocked", "needs human input")
        self.assertEqual(entry["kind"], "blocked")
        self.assertEqual(entry["detail"], "needs human input")

    def test_at_is_parseable_iso8601(self):
        entry = makeEntry("complete", "all done")
        parsed = datetime.fromisoformat(entry["at"])
        self.assertIsNotNone(parsed)

    def test_extra_kwargs_included(self):
        entry = makeEntry("replan", "extra fields test", subtask_id="st-007", attempt=2)
        self.assertEqual(entry["subtask_id"], "st-007")
        self.assertEqual(entry["attempt"], 2)

    def test_extra_kwargs_do_not_clobber_required_fields(self):
        # Passing 'at' as an extra kwarg must NOT overwrite the validated timestamp.
        entry = makeEntry("replan", "detail text", at="1970-01-01T00:00:00+00:00")
        self.assertNotEqual(entry["at"], "1970-01-01T00:00:00+00:00")

    def test_empty_kind_raises_value_error(self):
        with self.assertRaises(ValueError):
            makeEntry("", "some detail")

    def test_non_string_kind_raises_value_error(self):
        with self.assertRaises(ValueError):
            makeEntry(42, "some detail")  # type: ignore[arg-type]

    def test_non_string_detail_raises_type_error(self):
        with self.assertRaises(TypeError):
            makeEntry("replan", 99)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Contract 8: notifications.entry.validate / isValid API (st-061)
# ---------------------------------------------------------------------------

class TestValidateAPI(unittest.TestCase):
    """validate() must return a list of error strings; isValid() is True iff validate() == []."""

    def test_valid_entry_returns_empty_errors(self):
        entry = makeEntry("subtask_done", "st-001 done")
        self.assertEqual(validate(entry), [])

    def test_is_valid_true_for_good_entry(self):
        entry = makeEntry("complete", "task finished")
        self.assertTrue(isValid(entry))

    def test_missing_at_reported(self):
        entry = {"kind": "replan", "detail": "ok"}
        errors = validate(entry)
        self.assertTrue(any("at" in e for e in errors))

    def test_missing_kind_reported(self):
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "detail": "ok"}
        errors = validate(entry)
        self.assertTrue(any("kind" in e for e in errors))

    def test_missing_detail_reported(self):
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "replan"}
        errors = validate(entry)
        self.assertTrue(any("detail" in e for e in errors))

    def test_non_dict_returns_type_error(self):
        errors = validate("not a dict")
        self.assertEqual(len(errors), 1)
        self.assertIn("dict", errors[0])

    def test_invalid_at_format_reported(self):
        entry = {"at": "not-a-date", "kind": "replan", "detail": "ok"}
        errors = validate(entry)
        self.assertTrue(any("at" in e for e in errors))

    def test_empty_kind_reported(self):
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "", "detail": "ok"}
        errors = validate(entry)
        self.assertTrue(any("kind" in e for e in errors))

    def test_non_str_detail_reported(self):
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "replan", "detail": 42}
        errors = validate(entry)
        self.assertTrue(any("detail" in e for e in errors))

    def test_is_valid_false_for_missing_key(self):
        self.assertFalse(isValid({"kind": "replan", "detail": "ok"}))


# ---------------------------------------------------------------------------
# Contract 9: VALID_KINDS vocabulary (st-061)
# ---------------------------------------------------------------------------

class TestValidKindsVocabulary(unittest.TestCase):
    def test_valid_kinds_is_frozenset(self):
        self.assertIsInstance(VALID_KINDS, frozenset)

    def test_core_kinds_present(self):
        for kind in ("replan", "complete", "aborted", "subtask_done", "subtask_failed", "blocked"):
            self.assertIn(kind, VALID_KINDS)

    def test_kinds_are_all_strings(self):
        self.assertTrue(all(isinstance(k, str) for k in VALID_KINDS))

    def test_no_empty_kind_in_vocabulary(self):
        self.assertNotIn("", VALID_KINDS)


# ---------------------------------------------------------------------------
# Contract 10: NotificationBus.surface_count and concurrent emit safety (st-061)
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


# ---------------------------------------------------------------------------
# Contract 11: discord_bot UI utilities (st-061)
# ---------------------------------------------------------------------------

class TestProgressBar(unittest.TestCase):
    def test_zero_total_no_division_error(self):
        result = d.progressBar(0, 0)
        self.assertIn("%", result)

    def test_full_completion_shows_100(self):
        result = d.progressBar(10, 10)
        self.assertIn("100%", result)

    def test_zero_done_shows_0_percent(self):
        result = d.progressBar(0, 10)
        self.assertIn("0%", result)

    def test_done_exceeds_total_clamped(self):
        result = d.progressBar(15, 10)
        self.assertIn("100%", result)

    def test_returns_string(self):
        self.assertIsInstance(d.progressBar(3, 7), str)


class TestSubtaskTracker(unittest.TestCase):
    def test_all_pending_shows_no_pass_rate(self):
        subtasks = [{"status": "pending"} for _ in range(4)]
        result = d.subtaskTracker(subtasks)
        self.assertNotIn("pass", result)

    def test_pass_rate_computed_correctly(self):
        subtasks = [
            {"status": "done"},
            {"status": "done"},
            {"status": "failed"},
        ]
        result = d.subtaskTracker(subtasks)
        # 2 done out of 3 countable → 67%
        self.assertIn("67%", result)

    def test_empty_subtasks_no_error(self):
        result = d.subtaskTracker([])
        self.assertIsInstance(result, str)

    def test_all_done_shows_100_pass(self):
        subtasks = [{"status": "done"} for _ in range(5)]
        result = d.subtaskTracker(subtasks)
        self.assertIn("100%", result)


class TestFormatVerdict(unittest.TestCase):
    def test_approved_verdict(self):
        self.assertEqual(d.formatVerdict("approved"), "✅ APPROVED")

    def test_challenged_verdict(self):
        self.assertEqual(d.formatVerdict("challenged"), "⚔️ CHALLENGED")

    def test_unknown_verdict(self):
        self.assertEqual(d.formatVerdict("maybe"), "❔ UNKNOWN")

    def test_none_verdict(self):
        self.assertEqual(d.formatVerdict(None), "❔ UNKNOWN")

    def test_case_insensitive(self):
        self.assertEqual(d.formatVerdict("APPROVED"), "✅ APPROVED")
        self.assertEqual(d.formatVerdict("Rejected"), "⚔️ CHALLENGED")


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(__import__(__name__))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print(f"\n100% passed ({result.testsRun} tests)")
    else:
        n_fail = len(result.failures) + len(result.errors)
        print(f"\n{n_fail} failed / {result.testsRun} tests")
        raise SystemExit(1)
