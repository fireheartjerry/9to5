"""Notification system enhancements — Part B.

Covers:
  - Config notification flags / constants completeness
  - Module import platform_core.ops.health as health
  - Error handling robustness across surface types
  - Bus + entry pipeline health check

Split from test_notification_enhancements.py (was 400 lines).
"""
from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
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
# 6. Module import platform_core.ops.health as health
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
    import unittest as _ut
    loader = _ut.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = _ut.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
