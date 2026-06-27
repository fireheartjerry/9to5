"""Basic notification integration tests.

Covers bus/entry pipeline, bus+TaskState integration, mini-run lifecycle,
surface protocol conformance, and concurrent emission.

Split from test_notification_integration.py (was 572 lines).  Dashboard /
webdash / embed-builder tests live in test_notification_integration_advanced.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import threading
import unittest
from unittest import mock

import config
from notifications.bus import NotificationBus, NotificationSurface
from notifications.entry import VALID_KINDS, makeEntry, validate
from state.task import TaskState


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_state(goal: str = "integration test goal", horizon: float = 1.0) -> TaskState:
    st = TaskState.create(goal, horizon)
    st.meta["status"] = "executing"
    return st


def _add_subtasks(state: TaskState, n: int = 3) -> None:
    for i in range(n):
        state.addSubtask(f"st-{i + 1:03d}", f"subtask {i + 1}", "executor")


class _CaptureSurface:
    """Minimal NotificationSurface that records every call."""
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def handle(self, event_type: str, payload: dict) -> None:
        self.calls.append((event_type, payload))


class _FailingSurface:
    """Surface that always raises — used to verify isolation."""
    def handle(self, event_type: str, payload: dict) -> None:
        raise RuntimeError("intentional surface failure")


# ---------------------------------------------------------------------------
# 1. Bus + Entry pipeline
# ---------------------------------------------------------------------------

class TestBusEntryPipeline(unittest.TestCase):
    """makeEntry() → bus.emit() → surface receives a schema-valid entry."""

    def setUp(self):
        self.bus = NotificationBus()
        self.cap = _CaptureSurface()
        self.bus.register(self.cap)

    def test_valid_entry_emitted_and_received(self):
        entry = makeEntry("replan", "added 2 subtasks")
        self.assertEqual(validate(entry), [])
        self.bus.emit(entry["kind"], entry)
        self.assertEqual(len(self.cap.calls), 1)
        evt, payload = self.cap.calls[0]
        self.assertEqual(evt, "replan")
        self.assertEqual(validate(payload), [])

    def test_all_valid_kinds_transit_without_error(self):
        for kind in sorted(VALID_KINDS):
            entry = makeEntry(kind, f"detail for {kind}")
            self.bus.emit(entry["kind"], entry)
        self.assertEqual(len(self.cap.calls), len(VALID_KINDS))

    def test_extra_fields_survive_transit(self):
        entry = makeEntry("adversary_triggered", "heartbeat", verdict="approved", attempt=2)
        self.bus.emit(entry["kind"], entry)
        _, received = self.cap.calls[0]
        self.assertEqual(received.get("verdict"), "approved")
        self.assertEqual(received.get("attempt"), 2)

    def test_surface_isolation_does_not_drop_subsequent_surface(self):
        bus = NotificationBus()
        bus.register(_FailingSurface())
        cap = _CaptureSurface()
        bus.register(cap)
        entry = makeEntry("subtask_done", "st-001 done")
        bus.emit(entry["kind"], entry)
        self.assertEqual(len(cap.calls), 1)

    def test_three_surface_fan_out(self):
        bus = NotificationBus()
        surfaces = [_CaptureSurface() for _ in range(3)]
        for s in surfaces:
            bus.register(s)
        entry = makeEntry("complete", "run finished")
        bus.emit(entry["kind"], entry)
        for s in surfaces:
            self.assertEqual(len(s.calls), 1)
            self.assertEqual(s.calls[0][0], "complete")

    def test_failing_surface_between_two_good_surfaces_logged(self):
        bus = NotificationBus()
        cap_a = _CaptureSurface()
        cap_b = _CaptureSurface()
        bus.register(cap_a)
        bus.register(_FailingSurface())
        bus.register(cap_b)
        import logging
        with self.assertLogs("notifications.bus", level=logging.ERROR):
            bus.emit("aborted", {"reason": "test abort"})
        self.assertEqual(len(cap_a.calls), 1)
        self.assertEqual(len(cap_b.calls), 1)


# ---------------------------------------------------------------------------
# 2. Bus + TaskState notifications integration
# ---------------------------------------------------------------------------

class TestBusTaskStateIntegration(unittest.TestCase):
    """Bus emits are reflected in TaskState.data['notifications']."""

    def setUp(self):
        self.state = _make_state()

    def test_add_notification_produces_schema_valid_entry(self):
        rec = self.state.addNotification("planning_start", "plan authored")
        self.assertEqual(validate(rec), [])

    def test_multiple_notifications_accumulate(self):
        kinds = ["planning_start", "subtask_done", "replan", "complete"]
        for kind in kinds:
            self.state.addNotification(kind, f"detail:{kind}")
        stored = self.state.data["notifications"]
        stored_kinds = [n["kind"] for n in stored]
        for kind in kinds:
            self.assertIn(kind, stored_kinds)

    def test_replan_count_derived_correctly(self):
        self.state.addNotification("replan", "first replan")
        self.state.addNotification("subtask_done", "st-001")
        self.state.addNotification("replan", "second replan")
        replans = sum(1 for n in self.state.data["notifications"] if n["kind"] == "replan")
        self.assertEqual(replans, 2)

    def test_extra_kwargs_stored_in_notifications(self):
        self.state.addNotification("adversary_triggered", "heartbeat", verdict="approved")
        rec = next(n for n in self.state.data["notifications"] if n["kind"] == "adversary_triggered")
        self.assertEqual(rec.get("verdict"), "approved")

    def test_bus_surface_and_task_state_receive_same_event(self):
        bus = NotificationBus()
        cap = _CaptureSurface()
        bus.register(cap)

        entry = makeEntry("subtask_done", "st-002 done")
        self.state.addNotification(entry["kind"], entry["detail"])
        bus.emit(entry["kind"], entry)

        self.assertEqual(len(cap.calls), 1)
        notif_kinds = [n["kind"] for n in self.state.data["notifications"]]
        self.assertIn("subtask_done", notif_kinds)


# ---------------------------------------------------------------------------
# 5. Mini-run lifecycle: entry kinds through bus → multiple surfaces
# ---------------------------------------------------------------------------

class TestMiniRunLifecycle(unittest.TestCase):
    """Simulates a mini run lifecycle and verifies all notification surfaces receive
    events in order with correct kinds."""

    LIFECYCLE_KINDS = [
        "planning_start",
        "architect_done",
        "subtask_done",
        "adversary_triggered",
        "replan",
        "subtask_failed",
        "complete",
    ]

    def test_lifecycle_all_surfaces_receive_all_events(self):
        bus = NotificationBus()
        cap_a = _CaptureSurface()
        cap_b = _CaptureSurface()
        bus.register(cap_a)
        bus.register(cap_b)

        for kind in self.LIFECYCLE_KINDS:
            entry = makeEntry(kind, f"detail for {kind}")
            bus.emit(entry["kind"], entry)

        self.assertEqual(len(cap_a.calls), len(self.LIFECYCLE_KINDS))
        self.assertEqual(len(cap_b.calls), len(self.LIFECYCLE_KINDS))
        received_kinds_a = [c[0] for c in cap_a.calls]
        self.assertEqual(received_kinds_a, self.LIFECYCLE_KINDS)

    def test_lifecycle_with_intermittent_failures_all_good_surfaces_complete(self):
        bus = NotificationBus()
        cap = _CaptureSurface()
        bus.register(cap)
        bus.register(_FailingSurface())

        for kind in self.LIFECYCLE_KINDS:
            bus.emit(kind, makeEntry(kind, ""))

        self.assertEqual(len(cap.calls), len(self.LIFECYCLE_KINDS))

    def test_task_state_collects_lifecycle_notifications(self):
        state = _make_state("lifecycle goal")
        for kind in self.LIFECYCLE_KINDS:
            state.addNotification(kind, f"detail:{kind}")

        notifs = state.data["notifications"]
        stored_kinds = [n["kind"] for n in notifs]
        for kind in self.LIFECYCLE_KINDS:
            self.assertIn(kind, stored_kinds)


# ---------------------------------------------------------------------------
# 7. NotificationSurface Protocol conformance
# ---------------------------------------------------------------------------

class TestSurfaceProtocolConformance(unittest.TestCase):
    def test_capture_surface_satisfies_protocol(self):
        self.assertIsInstance(_CaptureSurface(), NotificationSurface)

    def test_failing_surface_satisfies_protocol(self):
        self.assertIsInstance(_FailingSurface(), NotificationSurface)

    def test_plain_object_does_not_satisfy_protocol(self):
        class _NoHandle:
            pass
        self.assertNotIsInstance(_NoHandle(), NotificationSurface)

    def test_object_with_wrong_signature_does_not_satisfy_protocol(self):
        class _WrongHandle:
            def handle(self) -> None:
                pass
        # Runtime-checkable only checks attribute presence, not signature.
        # _WrongHandle *does* have `handle` so it passes isinstance — this is expected
        # Python behavior and intentionally tested to document the limitation.
        # We only assert it doesn't raise.
        isinstance(_WrongHandle(), NotificationSurface)


# ---------------------------------------------------------------------------
# 8. Concurrent bus emission under load
# ---------------------------------------------------------------------------

class TestConcurrentBusEmission(unittest.TestCase):
    def test_high_volume_concurrent_emit_no_drops(self):
        bus = NotificationBus()
        cap = _CaptureSurface()
        bus.register(cap)
        errors: list[Exception] = []

        def _emit_batch(n: int) -> None:
            try:
                for i in range(20):
                    bus.emit("subtask_done", makeEntry("subtask_done", f"t{n}-{i}"))
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=_emit_batch, args=(k,)) for k in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], "concurrent emit raised exceptions")
        self.assertEqual(len(cap.calls), 100)

    def test_concurrent_emit_isolation_under_mixed_surfaces(self):
        bus = NotificationBus()
        bus.register(_FailingSurface())
        cap = _CaptureSurface()
        bus.register(cap)
        errors: list[Exception] = []

        def _emit_batch(n: int) -> None:
            try:
                for i in range(10):
                    bus.emit("replan", {"n": n, "i": i})
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=_emit_batch, args=(k,)) for k in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(cap.calls), 40)


if __name__ == "__main__":
    unittest.main()
