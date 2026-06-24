"""Tests for NotificationBus: delivery, surface isolation, edge cases, Protocol."""
from __future__ import annotations

import logging
import unittest

from notifications.bus import NotificationBus, NotificationSurface


class _CaptureSurface:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def handle(self, event_type: str, payload: dict) -> None:
        self.calls.append((event_type, payload))


class _FailingSurface:
    def handle(self, event_type: str, payload: dict) -> None:
        raise RuntimeError("intentional surface failure")


class TestNotificationBusRegistration(unittest.TestCase):
    def test_registered_surface_receives_event(self):
        bus = NotificationBus()
        cap = _CaptureSurface()
        bus.register(cap)
        bus.emit("subtask_done", {"subtask_id": "st-001"})
        self.assertEqual(len(cap.calls), 1)
        self.assertEqual(cap.calls[0][0], "subtask_done")
        self.assertEqual(cap.calls[0][1], {"subtask_id": "st-001"})

    def test_multiple_surfaces_all_receive_event(self):
        bus = NotificationBus()
        surfaces = [_CaptureSurface() for _ in range(4)]
        for s in surfaces:
            bus.register(s)
        bus.emit("replan", {"reason": "added subtask"})
        for s in surfaces:
            self.assertEqual(len(s.calls), 1)
            self.assertEqual(s.calls[0][0], "replan")

    def test_multiple_emits_all_delivered(self):
        bus = NotificationBus()
        cap = _CaptureSurface()
        bus.register(cap)
        for kind in ("planning_start", "subtask_done", "complete"):
            bus.emit(kind, {})
        self.assertEqual(len(cap.calls), 3)
        self.assertEqual([c[0] for c in cap.calls], ["planning_start", "subtask_done", "complete"])


class TestNotificationBusSurfaceIsolation(unittest.TestCase):
    def test_failing_surface_does_not_propagate(self):
        bus = NotificationBus()
        bus.register(_FailingSurface())
        bus.emit("subtask_done", {})  # must not raise

    def test_failing_surface_does_not_block_subsequent_surface(self):
        bus = NotificationBus()
        bus.register(_FailingSurface())
        cap = _CaptureSurface()
        bus.register(cap)
        bus.emit("blocked", {"reason": "test"})
        self.assertEqual(len(cap.calls), 1)

    def test_failing_surface_between_two_good_surfaces(self):
        bus = NotificationBus()
        cap_a = _CaptureSurface()
        cap_b = _CaptureSurface()
        bus.register(cap_a)
        bus.register(_FailingSurface())
        bus.register(cap_b)
        bus.emit("aborted", {})
        self.assertEqual(len(cap_a.calls), 1)
        self.assertEqual(len(cap_b.calls), 1)

    def test_failure_logged_not_silently_swallowed(self):
        bus = NotificationBus()
        bus.register(_FailingSurface())
        with self.assertLogs("notifications.bus", level=logging.ERROR):
            bus.emit("subtask_done", {})


class TestNotificationBusEdgeCases(unittest.TestCase):
    def test_empty_bus_emit_is_noop(self):
        bus = NotificationBus()
        bus.emit("anything", {})  # must not raise

    def test_emit_with_empty_payload(self):
        bus = NotificationBus()
        cap = _CaptureSurface()
        bus.register(cap)
        bus.emit("heartbeat", {})
        self.assertEqual(cap.calls[0][1], {})

    def test_emit_with_rich_payload(self):
        bus = NotificationBus()
        cap = _CaptureSurface()
        bus.register(cap)
        payload = {"subtask_id": "st-005", "attempt": 2, "nested": {"k": "v"}}
        bus.emit("subtask_failed", payload)
        self.assertIs(cap.calls[0][1], payload)

    def test_register_same_surface_twice_delivers_twice(self):
        bus = NotificationBus()
        cap = _CaptureSurface()
        bus.register(cap)
        bus.register(cap)
        bus.emit("replan", {})
        self.assertEqual(len(cap.calls), 2)


class TestNotificationSurfaceProtocol(unittest.TestCase):
    def test_capture_surface_satisfies_protocol(self):
        self.assertIsInstance(_CaptureSurface(), NotificationSurface)

    def test_failing_surface_satisfies_protocol(self):
        self.assertIsInstance(_FailingSurface(), NotificationSurface)

    def test_object_without_handle_does_not_satisfy_protocol(self):
        class _NoHandle:
            pass
        self.assertNotIsInstance(_NoHandle(), NotificationSurface)


if __name__ == "__main__":
    unittest.main()
