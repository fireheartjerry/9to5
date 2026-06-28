"""Notification system enhancements — merged.

Covers:
  Part A:
  - NotificationBus.surface_count property
  - notifications.entry.isValid() convenience helper
  - Entry JSON roundtrip
  - Audit trail integration (entries are JSON-serialisable)

  Part B:
  - Config notification flags / constants completeness
  - Module import platform_core.ops.health as health
  - Error handling robustness across surface types
  - Bus + entry pipeline health check
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
import notifications.audit as audit
from notifications.bus import NotificationBus, NotificationSurface
from notifications.entry import VALID_KINDS, isValid, makeEntry, validate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Cap:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def handle(self, event_type: str, payload: dict) -> None:
        self.calls.append((event_type, payload))


class _Fail:
    def handle(self, event_type: str, payload: dict) -> None:
        raise ValueError("intentional failure")


class _SlowFail:
    """Raises a non-standard exception type."""
    def handle(self, event_type: str, payload: dict) -> None:
        raise SystemExit(1)  # extreme — must still be caught


# ---------------------------------------------------------------------------
# 1. surface_count property
# ---------------------------------------------------------------------------

class TestSurfaceCount(unittest.TestCase):
    def test_empty_bus_count_is_zero(self):
        bus = NotificationBus()
        self.assertEqual(bus.surface_count, 0)

    def test_count_increments_per_registration(self):
        bus = NotificationBus()
        for i in range(5):
            bus.register(_Cap())
            self.assertEqual(bus.surface_count, i + 1)

    def test_same_surface_registered_twice_counts_twice(self):
        bus = NotificationBus()
        cap = _Cap()
        bus.register(cap)
        bus.register(cap)
        self.assertEqual(bus.surface_count, 2)

    def test_count_unchanged_after_emit(self):
        bus = NotificationBus()
        bus.register(_Cap())
        bus.emit("replan", {})
        self.assertEqual(bus.surface_count, 1)

    def test_count_unchanged_after_failing_emit(self):
        bus = NotificationBus()
        bus.register(_Fail())
        try:
            bus.emit("replan", {})
        except Exception:  # noqa: BLE001
            pass
        self.assertEqual(bus.surface_count, 1)


# ---------------------------------------------------------------------------
# 2. isValid() convenience helper
# ---------------------------------------------------------------------------

class TestIsValid(unittest.TestCase):
    def test_valid_entry_returns_true(self):
        entry = makeEntry("complete", "run finished")
        self.assertTrue(isValid(entry))

    def test_missing_key_returns_false(self):
        self.assertFalse(isValid({"kind": "replan", "detail": "x"}))

    def test_bad_at_returns_false(self):
        self.assertFalse(isValid({"at": "not-a-date", "kind": "replan", "detail": "x"}))

    def test_empty_kind_returns_false(self):
        self.assertFalse(isValid({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": "",
            "detail": "x",
        }))

    def test_non_dict_returns_false(self):
        self.assertFalse(isValid("not-a-dict"))  # type: ignore[arg-type]

    def test_all_valid_kinds_return_true(self):
        for kind in VALID_KINDS:
            with self.subTest(kind=kind):
                self.assertTrue(isValid(makeEntry(kind, "detail")))

    def test_isvalid_consistent_with_validate(self):
        entries = [
            makeEntry("replan", "x"),
            {"kind": "bad", "detail": "x"},
            {"at": "2026-01-01T00:00:00+00:00", "kind": "complete", "detail": "ok"},
        ]
        for entry in entries:
            with self.subTest(entry=entry):
                self.assertEqual(isValid(entry), validate(entry) == [])


# ---------------------------------------------------------------------------
# 3. Entry JSON roundtrip
# ---------------------------------------------------------------------------

class TestEntryJsonRoundtrip(unittest.TestCase):
    def test_entry_is_json_serialisable(self):
        entry = makeEntry("subtask_done", "st-001 completed", attempt=1)
        serialised = json.dumps(entry)
        self.assertIsInstance(serialised, str)

    def test_roundtrip_preserves_required_fields(self):
        entry = makeEntry("replan", "added 2 subtasks")
        restored = json.loads(json.dumps(entry))
        self.assertTrue(isValid(restored))
        self.assertEqual(restored["kind"], entry["kind"])
        self.assertEqual(restored["detail"], entry["detail"])
        self.assertEqual(restored["at"], entry["at"])

    def test_roundtrip_preserves_extra_fields(self):
        entry = makeEntry("adversary_triggered", "heartbeat", verdict="approved", attempt=3)
        restored = json.loads(json.dumps(entry))
        self.assertEqual(restored["verdict"], "approved")
        self.assertEqual(restored["attempt"], 3)

    def test_entry_at_is_utc(self):
        entry = makeEntry("complete", "done")
        parsed = datetime.fromisoformat(entry["at"])
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)


# ---------------------------------------------------------------------------
# 4. Audit integration
# ---------------------------------------------------------------------------

class TestAuditIntegration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._path = Path(self._tmp) / "audit.jsonl"
        self._patch = mock.patch.object(config, "AUDIT_LOG_PATH", self._path)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_record_produces_json_line(self):
        audit.record(123, "abort", "task-1", "web button")
        lines = self._path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        row = json.loads(lines[0])
        self.assertEqual(row["action"], "abort")
        self.assertEqual(row["user_id"], "123")
        self.assertEqual(row["task_id"], "task-1")
        self.assertEqual(row["detail"], "web button")

    def test_record_entry_has_at_field(self):
        audit.record(1, "pause", "task-x")
        row = json.loads(self._path.read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("at", row)
        datetime.fromisoformat(row["at"])  # must not raise

    def test_recent_returns_n_entries(self):
        for i in range(10):
            audit.record(i, f"action-{i}", "t")
        result = audit.recent(5)
        self.assertEqual(len(result), 5)

    def test_recent_empty_on_missing_file(self):
        missing = Path(self._tmp) / "no_such_file.jsonl"
        with mock.patch.object(config, "AUDIT_LOG_PATH", missing):
            self.assertEqual(audit.recent(), [])

    def test_record_does_not_raise_on_bad_path(self):
        bad = Path(self._tmp) / "nonexistent_dir" / "deep" / "audit.jsonl"
        with mock.patch.object(config, "AUDIT_LOG_PATH", bad):
            audit.record(1, "abort", "t")  # must not raise

    def test_multiple_records_accumulate(self):
        for action in ("abort", "pause", "resume"):
            audit.record(1, action, "t")
        result = audit.recent(10)
        self.assertEqual(len(result), 3)
        self.assertEqual([r["action"] for r in result], ["abort", "pause", "resume"])


# ---------------------------------------------------------------------------
# 5. Config notification constants completeness
# ---------------------------------------------------------------------------

class TestConfigNotificationConstants(unittest.TestCase):
    def test_discord_dashboard_is_bool(self):
        self.assertIsInstance(config.DISCORD_DASHBOARD, bool)

    def test_web_dashboard_is_bool(self):
        self.assertIsInstance(config.WEB_DASHBOARD, bool)

    def test_web_dashboard_port_in_valid_range(self):
        self.assertGreater(config.WEB_DASHBOARD_PORT, 1024)
        self.assertLess(config.WEB_DASHBOARD_PORT, 65536)

    def test_discord_rest_timeout_positive(self):
        self.assertGreater(config.DISCORD_REST_TIMEOUT, 0)

    def test_discord_poll_seconds_positive(self):
        self.assertGreater(config.DISCORD_POLL_SECONDS, 0)

    def test_audit_log_path_is_path(self):
        self.assertIsInstance(config.AUDIT_LOG_PATH, Path)

    def test_audit_max_bytes_positive(self):
        self.assertGreater(config.AUDIT_MAX_BYTES, 0)

    def test_discord_limits_are_positive_ints(self):
        for name in (
            "DISCORD_MAX_CONTENT",
            "DISCORD_MAX_EMBED_DESC",
            "DISCORD_MAX_FIELD_NAME",
            "DISCORD_MAX_FIELD_VALUE",
            "DISCORD_EMBED_TOTAL_MAX",
        ):
            val = getattr(config, name)
            with self.subTest(name=name):
                self.assertIsInstance(val, int)
                self.assertGreater(val, 0)

    def test_status_colors_covers_lifecycle(self):
        for status in ("executing", "planning", "done", "complete", "failed", "aborted", "paused"):
            with self.subTest(status=status):
                self.assertIn(status, config.STATUS_COLORS)


# ---------------------------------------------------------------------------
# 6. Module import health
# ---------------------------------------------------------------------------

class TestModuleImportHealth(unittest.TestCase):
    def test_bus_importable(self):
        import notifications.bus  # noqa: F401

    def test_entry_importable(self):
        import notifications.entry  # noqa: F401

    def test_audit_importable(self):
        import notifications.audit  # noqa: F401

    def test_dashboard_importable(self):
        import notifications.dashboard  # noqa: F401

    def test_webdash_importable(self):
        import notifications.webdash  # noqa: F401

    def test_entry_exports_expected_names(self):
        import notifications.entry as e
        for name in ("VALID_KINDS", "REQUIRED_KEYS", "makeEntry", "validate", "isValid"):
            self.assertTrue(hasattr(e, name), f"entry missing {name!r}")

    def test_bus_exports_expected_names(self):
        import notifications.bus as b
        for name in ("NotificationBus", "NotificationSurface"):
            self.assertTrue(hasattr(b, name), f"bus missing {name!r}")


# ---------------------------------------------------------------------------
# 7. Error handling robustness
# ---------------------------------------------------------------------------

class TestErrorHandlingRobustness(unittest.TestCase):
    def test_system_exit_in_surface_caught(self):
        """Even SystemExit must not propagate out of bus.emit."""
        bus = NotificationBus()
        bus.register(_SlowFail())
        cap = _Cap()
        bus.register(cap)
        try:
            bus.emit("replan", {})
        except SystemExit:
            self.fail("bus.emit let SystemExit propagate")
        self.assertEqual(len(cap.calls), 1)

    def test_exception_in_surface_does_not_corrupt_payload(self):
        bus = NotificationBus()
        cap = _Cap()
        bus.register(_Fail())
        bus.register(cap)
        payload = {"x": 1}
        bus.emit("replan", payload)
        self.assertIs(cap.calls[0][1], payload)

    def test_concurrent_registration_and_emit(self):
        bus = NotificationBus()
        errors: list[Exception] = []

        def _register() -> None:
            try:
                for _ in range(10):
                    bus.register(_Cap())
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        cap = _Cap()
        bus.register(cap)

        threads = [threading.Thread(target=_register) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])

    def test_emit_with_none_payload_values(self):
        bus = NotificationBus()
        cap = _Cap()
        bus.register(cap)
        bus.emit("subtask_done", {"result": None, "error": None})
        self.assertEqual(cap.calls[0][1]["result"], None)

    def test_entry_detail_unicode(self):
        entry = makeEntry("complete", "done 完成 🎉")
        self.assertTrue(isValid(entry))
        self.assertEqual(entry["detail"], "done 完成 🎉")

    def test_entry_very_long_detail_valid(self):
        entry = makeEntry("subtask_failed", "x" * 10_000)
        self.assertTrue(isValid(entry))


# ---------------------------------------------------------------------------
# 8. Bus + entry pipeline health check
# ---------------------------------------------------------------------------

class TestBusEntryHealth(unittest.TestCase):
    def test_surface_count_matches_fan_out(self):
        bus = NotificationBus()
        caps = [_Cap() for _ in range(7)]
        for c in caps:
            bus.register(c)
        self.assertEqual(bus.surface_count, 7)
        bus.emit("complete", makeEntry("complete", "all done"))
        for c in caps:
            self.assertEqual(len(c.calls), 1)

    def test_isvalid_used_as_bus_gate(self):
        """Emit only if entry is valid — pattern guard."""
        bus = NotificationBus()
        cap = _Cap()
        bus.register(cap)
        good = makeEntry("replan", "valid entry")
        bad = {"kind": "replan"}  # missing required keys
        if isValid(good):
            bus.emit(good["kind"], good)
        if isValid(bad):
            bus.emit(bad["kind"], bad)  # type: ignore[arg-type]
        self.assertEqual(len(cap.calls), 1)
        self.assertEqual(cap.calls[0][0], "replan")


if __name__ == "__main__":
    unittest.main()
