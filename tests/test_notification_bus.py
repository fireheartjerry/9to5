"""Tests for NotificationBus error-handling and fan-out behaviour."""
import logging
import pathlib
import sys
import unittest

# Allow direct invocation: python C:\9to5\tests\test_notification_bus.py
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from notifications.bus import NotificationBus, NotificationSurface


class _OkSurface:
    def __init__(self):
        self.calls: list = []

    def handle(self, event_type: str, payload: dict) -> None:
        self.calls.append((event_type, payload))


class _RaisingSurface:
    def __init__(self, exc):
        self._exc = exc
        self.calls = 0

    def handle(self, event_type: str, payload: dict) -> None:
        self.calls += 1
        raise self._exc


class TestNotificationBusErrorHandling(unittest.TestCase):
    def test_surface_exception_does_not_propagate(self):
        bus = NotificationBus()
        bus.register(_RaisingSurface(RuntimeError("boom")))
        bus.emit("subtask_done", {})

    def test_downstream_surface_still_called_after_upstream_raises(self):
        bus = NotificationBus()
        bad = _RaisingSurface(ValueError("bad surface"))
        good = _OkSurface()
        bus.register(bad)
        bus.register(good)
        bus.emit("replan", {"detail": "test"})
        self.assertEqual(len(good.calls), 1)
        self.assertEqual(good.calls[0][0], "replan")

    def test_keyboard_interrupt_inside_surface_propagates(self):
        # B17: BaseException (interrupt/shutdown) must NOT be eaten by a surface.
        bus = NotificationBus()
        bus.register(_RaisingSurface(KeyboardInterrupt()))
        with self.assertRaises(KeyboardInterrupt):
            bus.emit("complete", {})

    def test_system_exit_inside_surface_propagates(self):
        # B17: SystemExit must propagate so shutdown is never silently swallowed.
        bus = NotificationBus()
        bus.register(_RaisingSurface(SystemExit(1)))
        with self.assertRaises(SystemExit):
            bus.emit("aborted", {})

    def test_error_logged_as_warning(self):
        bus = NotificationBus()
        bus.register(_RaisingSurface(RuntimeError("logged")))
        with self.assertLogs("notifications.bus", level=logging.WARNING):
            bus.emit("subtask_failed", {})

    def test_multiple_surfaces_all_receive_event(self):
        bus = NotificationBus()
        s1, s2, s3 = _OkSurface(), _OkSurface(), _OkSurface()
        for s in (s1, s2, s3):
            bus.register(s)
        bus.emit("planning_start", {"goal": "test"})
        for s in (s1, s2, s3):
            self.assertEqual(len(s.calls), 1)

    def test_surface_count(self):
        bus = NotificationBus()
        self.assertEqual(bus.surface_count, 0)
        bus.register(_OkSurface())
        self.assertEqual(bus.surface_count, 1)
        bus.register(_OkSurface())
        self.assertEqual(bus.surface_count, 2)

    def test_empty_bus_emit_is_noop(self):
        bus = NotificationBus()
        bus.emit("architect_done", {"path": "architect.md"})

    def test_protocol_isinstance_check(self):
        ok = _OkSurface()
        self.assertIsInstance(ok, NotificationSurface)

    def test_raising_surface_still_counted_as_called(self):
        bus = NotificationBus()
        bad = _RaisingSurface(Exception("err"))
        bus.register(bad)
        bus.emit("blocked", {})
        self.assertEqual(bad.calls, 1)

    def test_payload_passed_through_unmodified(self):
        bus = NotificationBus()
        s = _OkSurface()
        bus.register(s)
        payload = {"subtask_id": "st-003", "title": "Add tests"}
        bus.emit("subtask_done", payload)
        self.assertEqual(s.calls[0][1], payload)

    def test_multiple_emits_accumulate_on_surface(self):
        bus = NotificationBus()
        s = _OkSurface()
        bus.register(s)
        for evt in ("planning_start", "subtask_done", "complete"):
            bus.emit(evt, {})
        self.assertEqual(len(s.calls), 3)
        self.assertEqual([c[0] for c in s.calls], ["planning_start", "subtask_done", "complete"])


if __name__ == "__main__":
    unittest.main()
