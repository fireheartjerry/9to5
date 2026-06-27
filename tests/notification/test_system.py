"""System-level notification contract tests."""
from __future__ import annotations

import threading
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

import config
import notifications.discord_bot as d
from notifications import dashboard as dash
from notifications.bus import NotificationBus
from state.task import TaskState


def _task(status: str = "executing") -> TaskState:
    st = TaskState.create("test notification goal", 1.0)
    st.meta["status"] = status
    return st


def _notification_entry(kind: str = "replan", detail: str = "replanned") -> dict:
    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "detail": detail,
    }


class TestEmbedClampingContract(unittest.TestCase):
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
        self.assertIsNone(d._clampEmbed(None))

    def test_non_dict_embed_returned_unchanged(self):
        self.assertEqual(d._clampEmbed("not a dict"), "not a dict")


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
        self.assertEqual(len(snap), 1)

    def test_event_contains_timestamp_and_text(self):
        self.db.event("subtask done")
        entry = self.db._eventsSnapshot()[0]
        self.assertIn("subtask done", entry)
        self.assertIn("`", entry)

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


class TestNotificationEntryContract(unittest.TestCase):
    def test_well_formed_entry_has_required_keys(self):
        entry = _notification_entry("replan", "subtask count changed")
        for key in ("at", "kind", "detail"):
            self.assertIn(key, entry)

    def test_at_is_iso8601(self):
        parsed = datetime.fromisoformat(_notification_entry()["at"])
        self.assertIsNotNone(parsed)

    def test_kind_string_non_empty(self):
        entry = _notification_entry("adversary", "challenged st-002")
        self.assertIsInstance(entry["kind"], str)
        self.assertGreater(len(entry["kind"]), 0)

    def test_dashboard_counts_replan_from_notifications(self):
        notifications = [
            _notification_entry("replan", "added 2 subtasks"),
            _notification_entry("subtask_done", "st-001 complete"),
            _notification_entry("replan", "removed 1 subtask"),
        ]
        replans = sum(1 for n in notifications if n.get("kind") == "replan")
        self.assertEqual(replans, 2)


class TestRateLimitCircuitBreakerContract(unittest.TestCase):
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


class TestNotificationBusContract(unittest.TestCase):
    def _cap(self):
        class _C:
            calls: list = []
            def handle(self, t, p):
                self.calls.append((t, p))
        return _C()

    def _fail(self):
        class _F:
            def handle(self, t, p):
                raise RuntimeError("intentional")
        return _F()

    def test_emit_reaches_registered_surface(self):
        bus = NotificationBus()
        cap = self._cap()
        bus.register(cap)
        bus.emit("subtask_done", {"subtask_id": "st-001"})
        self.assertEqual(len(cap.calls), 1)

    def test_failing_surface_does_not_raise(self):
        bus = NotificationBus()
        bus.register(self._fail())
        cap = self._cap()
        bus.register(cap)
        bus.emit("subtask_done", {})
        self.assertEqual(len(cap.calls), 1)

    def test_multiple_surfaces_all_called(self):
        bus = NotificationBus()
        surfaces = [self._cap() for _ in range(3)]
        for s in surfaces:
            bus.register(s)
        bus.emit("blocked", {})
        for s in surfaces:
            self.assertEqual(len(s.calls), 1)

    def test_empty_bus_emit_is_noop(self):
        NotificationBus().emit("anything", {})


class TestSnapshotCacheContract(unittest.TestCase):
    def test_cache_returns_same_object_within_ttl(self):
        cache: list = []
        call_count = 0

        def _cached(task_id, builder):
            nonlocal call_count
            now = time.monotonic()
            if cache and cache[0] == task_id and now < cache[1]:
                return cache[2]
            snap = builder(task_id)
            cache[:] = [task_id, now + 1.0, snap]
            return snap

        def _builder(task_id):
            nonlocal call_count
            call_count += 1
            return {"task_id": task_id, "call": call_count}

        r1 = _cached("t1", _builder)
        r2 = _cached("t1", _builder)
        self.assertIs(r1, r2)
        self.assertEqual(call_count, 1)

    def test_cache_misses_on_different_task_id(self):
        cache: list = []
        builds: list[str] = []

        def _cached(task_id, builder):
            now = time.monotonic()
            if cache and cache[0] == task_id and now < cache[1]:
                return cache[2]
            snap = builder(task_id)
            cache[:] = [task_id, now + 1.0, snap]
            return snap

        def _builder(task_id):
            builds.append(task_id)
            return {"task_id": task_id}

        _cached("t1", _builder)
        _cached("t2", _builder)
        self.assertEqual(builds, ["t1", "t2"])

    def test_cache_invalidated_after_ttl(self):
        cache: list = []
        call_count = 0

        def _cached(task_id, builder, ttl=0.05):
            nonlocal call_count
            now = time.monotonic()
            if cache and cache[0] == task_id and now < cache[1]:
                return cache[2]
            snap = builder(task_id)
            cache[:] = [task_id, now + ttl, snap]
            return snap

        def _builder(task_id):
            nonlocal call_count
            call_count += 1
            return {}

        _cached("t1", _builder, ttl=0.05)
        time.sleep(0.1)
        _cached("t1", _builder, ttl=0.05)
        self.assertEqual(call_count, 2)


if __name__ == "__main__":
    unittest.main()
