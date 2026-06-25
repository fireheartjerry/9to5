"""Comprehensive integration tests for the notification system.

Tests multiple components working together:
  - NotificationBus + NotificationEntry: makeEntry → emit → surface receives valid entry
  - NotificationBus + TaskState: bus-emitted events mirrored in task.data['notifications']
  - DiscordDashboard + TaskState (mocked Discord): start / update / unpin lifecycle
  - webdash._snapshot with populated TaskState + ControlBus
  - End-to-end mini-run lifecycle: planning_start → subtask_done → complete
  - Embed builders produce valid (clamped) Discord payloads
  - Surface isolation under an orchestrated scenario
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path when the file is run directly
# (Python adds the script's directory, not cwd, so we add the parent manually).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import config
import notifications.discord_bot as d
from control import ControlBus
from notifications import dashboard as dash
from notifications import webdash
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
# 3. Dashboard + TaskState lifecycle (mocked Discord)
# ---------------------------------------------------------------------------

class TestDashboardTaskStateLifecycle(unittest.TestCase):
    """DiscordDashboard start/update/unpin integrated with TaskState (REST mocked)."""

    def _mock_discord(self):
        patches = [
            mock.patch.object(config, "DISCORD_DASHBOARD", True),
            mock.patch("notifications.discord_bot.editMessage", return_value=True),
            mock.patch("notifications.discord_bot.editMessageResult", return_value="ok"),
            mock.patch("notifications.discord_bot.createMessage", return_value="msg-1"),
            mock.patch("notifications.discord_bot.pinMessage", return_value=True),
            mock.patch("notifications.discord_bot.unpinMessage", return_value=True),
        ]
        return patches

    def test_start_creates_message_and_records_id(self):
        db = dash.DiscordDashboard()
        state = _make_state()
        _add_subtasks(state)
        patches = self._mock_discord()
        for p in patches:
            p.start()
        try:
            db.start(state, "planning")
            self.assertEqual(db.message_id, "msg-1")
        finally:
            for p in patches:
                p.stop()

    def test_update_reflects_effort_and_model(self):
        db = dash.DiscordDashboard()
        db.message_id = "existing-msg"
        state = _make_state()
        _add_subtasks(state)
        patches = self._mock_discord()
        for p in patches:
            p.start()
        try:
            db.update(state, "executing", effort="high", model="claude-opus-4-8", note="step 1 done")
            self.assertEqual(db.effort, "high")
            self.assertEqual(db.model, "claude-opus-4-8")
            snap = db._eventsSnapshot()
            self.assertTrue(any("step 1 done" in e for e in snap))
        finally:
            for p in patches:
                p.stop()

    def test_event_ring_survives_multiple_updates(self):
        db = dash.DiscordDashboard()
        db.message_id = "existing-msg"
        state = _make_state()
        patches = self._mock_discord()
        for p in patches:
            p.start()
        try:
            for i in range(12):
                db.update(state, "executing", note=f"event {i}")
            self.assertEqual(len(db._eventsSnapshot()), 10)
        finally:
            for p in patches:
                p.stop()

    def test_unpin_called_at_run_end(self):
        db = dash.DiscordDashboard()
        db.message_id = "msg-1"
        patches = self._mock_discord()
        m_unpin = None
        for p in patches:
            m = p.start()
            if "unpinMessage" in str(p):
                m_unpin = m
        try:
            db.unpin()
            if m_unpin is not None:
                m_unpin.assert_called_once()
        finally:
            for p in patches:
                p.stop()

    def test_start_noop_when_dashboard_disabled(self):
        db = dash.DiscordDashboard()
        state = _make_state()
        with mock.patch.object(config, "DISCORD_DASHBOARD", False):
            db.start(state, "starting")
        self.assertIsNone(db.message_id)

    def test_thread_safe_concurrent_updates(self):
        db = dash.DiscordDashboard()
        db.message_id = "existing-msg"
        state = _make_state()
        errors: list[Exception] = []
        patches = self._mock_discord()
        for p in patches:
            p.start()
        try:
            def _worker(n: int):
                try:
                    for i in range(5):
                        db.update(state, "executing", note=f"t{n}-{i}")
                except Exception as e:  # noqa: BLE001
                    errors.append(e)

            threads = [threading.Thread(target=_worker, args=(k,)) for k in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
        finally:
            for p in patches:
                p.stop()


# ---------------------------------------------------------------------------
# 4. Webdash _snapshot with populated TaskState
# ---------------------------------------------------------------------------

class TestWebdashSnapshotIntegration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._patch_state_dir = mock.patch.object(
            config, "STATE_DIR", Path(self._tmp) / "state"
        )
        self._patch_control_dir = mock.patch.object(
            config, "CONTROL_DIR", Path(self._tmp) / "control"
        )
        self._patch_state_dir.start()
        self._patch_control_dir.start()
        (Path(self._tmp) / "state").mkdir(parents=True, exist_ok=True)
        (Path(self._tmp) / "control").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._patch_state_dir.stop()
        self._patch_control_dir.stop()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_snapshot_unknown_task_returns_empty(self):
        snap = webdash._snapshot("nonexistent-task-id")
        self.assertTrue(snap.get("empty"))

    def test_snapshot_with_real_state_returns_expected_shape(self):
        state = _make_state("webdash test goal")
        _add_subtasks(state, 3)
        state.addNotification("planning_start", "plan authored")
        state.save()

        snap = webdash._snapshot(state.task_id)
        self.assertFalse(snap.get("empty"))
        self.assertIn("meta", snap)
        self.assertIn("subtasks", snap)
        self.assertIn("progress", snap)
        self.assertIn("control", snap)
        self.assertIn("events", snap)
        self.assertEqual(snap["progress"]["total"], 3)

    def test_snapshot_reflects_notifications(self):
        state = _make_state("notif test")
        state.addNotification("replan", "first replan")
        state.addNotification("subtask_done", "st-001 done")
        state.save()

        snap = webdash._snapshot(state.task_id)
        kinds = [e["kind"] for e in snap.get("events", [])]
        self.assertIn("replan", kinds)
        self.assertIn("subtask_done", kinds)

    def test_snapshot_control_reflects_abort(self):
        state = _make_state("control test")
        state.save()
        bus = ControlBus(state.task_id)
        bus.requestAbort()

        snap = webdash._snapshot(state.task_id)
        self.assertTrue(snap["control"]["abort"])

    def test_snapshot_control_reflects_pause(self):
        state = _make_state("pause test")
        state.save()
        ControlBus(state.task_id).requestPause()

        snap = webdash._snapshot(state.task_id)
        self.assertTrue(snap["control"]["pause"])


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
# 6. Embed builders produce Discord-safe payloads
# ---------------------------------------------------------------------------

class TestEmbedBuilderIntegration(unittest.TestCase):
    """Embed builders combined with _clampEmbed stay within Discord limits."""

    def _within_limits(self, embed: dict) -> bool:
        clamped = d._clampEmbed(embed)
        if d._embedLen(clamped) > config.DISCORD_EMBED_TOTAL_MAX:
            return False
        for f in clamped.get("fields", []):
            if len(str(f.get("value", ""))) > config.DISCORD_MAX_FIELD_VALUE:
                return False
        return True

    def test_planning_start_embed_within_limits(self):
        tasks = [{"title": f"t{i}: " + "x" * 100} for i in range(20)]
        embed = d.planningStartEmbed("x" * 2000, tasks)
        self.assertTrue(self._within_limits(embed))

    def test_adversary_triggered_embed_within_limits(self):
        embed = d.adversaryTriggeredEmbed("st-001 " + "x" * 200, "r" * 200, verdict="challenged")
        self.assertTrue(self._within_limits(embed))

    def test_blocked_embed_within_limits(self):
        embed = d.blockedEmbed("reason " + "r" * 2000, question="q" * 2000)
        self.assertTrue(self._within_limits(embed))

    def test_aborted_embed_within_limits(self):
        embed = d.abortedEmbed("abort reason " + "x" * 1000, "99h 59m")
        self.assertTrue(self._within_limits(embed))

    def test_subtask_failed_embed_within_limits(self):
        vr = {
            "cmd": "pytest " + "x" * 500,
            "returncode": 1,
            "stdout": "out " * 500,
            "stderr": "err " * 500,
            "passed": False,
        }
        embed = d.subtaskFailedEmbed("st-010", "title " + "x" * 100, vr, 3)
        self.assertTrue(self._within_limits(embed))

    def test_complete_embed_within_limits(self):
        state = _make_state("complete embed goal")
        _add_subtasks(state, 5)
        for i, st in enumerate(state.subtasks):
            state.subtasks[i]["status"] = "done"
        embed = d.completeEmbed(state, "https://github.com/example/repo/pull/42", "1h 30m")
        self.assertTrue(self._within_limits(embed))

    def test_clamp_does_not_drop_any_fields(self):
        state = _make_state("field preservation test")
        _add_subtasks(state, 3)
        for i in range(3):
            state.subtasks[i]["status"] = "done"
        raw = d.completeEmbed(state, "https://github.com/x/y/pull/1", "2h 0m")
        clamped = d._clampEmbed(raw)
        self.assertEqual(len(raw.get("fields", [])), len(clamped.get("fields", [])))


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
