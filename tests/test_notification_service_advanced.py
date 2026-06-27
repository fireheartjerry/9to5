"""Behavioral unit tests for notification service – dashboard lifecycle and command routing.

Covers:
  - notifications/dashboard.py  (DiscordDashboard._elapsed, event deque,
    _eventsSnapshot, update lifecycle)
  - notifications/command_bot.py  (handleCommand routing)

Design constraints:
  - No real network calls (all Discord REST mocked).
  - No real Discord.py imports required (tested pure-Python paths only).
  - Tests cover happy path, edge cases, and error/invalid-input scenarios.
  - Behavioral scenarios are deterministic; no timing or ordering flakiness.
"""
from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import config
from notifications import command_bot, commands
from notifications import dashboard as dash
from state.task import TaskState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task(status: str = "executing") -> TaskState:
    st = TaskState.create("test goal", 1.0)
    st.meta["status"] = status
    return st


# ---------------------------------------------------------------------------
# dashboard – DiscordDashboard
# ---------------------------------------------------------------------------

class TestDashboardElapsed(unittest.TestCase):
    """_elapsed is a static method -- unit-testable without a real Discord connection."""

    def _e(self, *args):
        return dash.DiscordDashboard._elapsed(*args)

    def test_none_returns_dash(self):
        self.assertEqual(self._e(None), "—")

    def test_empty_string_returns_dash(self):
        self.assertEqual(self._e(""), "—")

    def test_seconds_format(self):
        # a recent timestamp returns Xs
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(seconds=45)).isoformat()
        result = self._e(recent)
        self.assertRegex(result, r"\d+s")

    def test_minutes_format(self):
        now = datetime.now(timezone.utc)
        past = (now - timedelta(minutes=7)).isoformat()
        result = self._e(past)
        self.assertRegex(result, r"\d+m")

    def test_hours_and_minutes_format(self):
        now = datetime.now(timezone.utc)
        past = (now - timedelta(hours=2, minutes=15)).isoformat()
        result = self._e(past)
        self.assertRegex(result, r"\d+h \d+m")

    def test_invalid_iso_returns_dash(self):
        self.assertEqual(self._e("not-a-date"), "—")

    def test_negative_clamp_to_zero_seconds(self):
        # future timestamp: should not raise, should return "0s"
        now = datetime.now(timezone.utc)
        future = (now + timedelta(minutes=10)).isoformat()
        result = self._e(future)
        self.assertEqual(result, "0s")


class TestDashboardEventDeque(unittest.TestCase):
    def setUp(self):
        self.db = dash.DiscordDashboard()

    def test_event_appended(self):
        self.db.event("phase started")
        snapshot = self.db._eventsSnapshot()
        self.assertEqual(len(snapshot), 1)
        self.assertIn("phase started", snapshot[0])

    def test_timestamp_prepended(self):
        self.db.event("something")
        snapshot = self.db._eventsSnapshot()
        # format: `HH:MM:SS` <text>
        self.assertIn("`", snapshot[0])

    def test_maxlen_ten(self):
        for i in range(15):
            self.db.event(f"event {i}")
        snapshot = self.db._eventsSnapshot()
        self.assertEqual(len(snapshot), 10)

    def test_snapshot_returns_list_copy(self):
        self.db.event("a")
        snap1 = self.db._eventsSnapshot()
        self.db.event("b")
        snap2 = self.db._eventsSnapshot()
        # first snapshot must not be mutated retroactively
        self.assertEqual(len(snap1), 1)
        self.assertEqual(len(snap2), 2)

    def test_thread_safe_concurrent_events(self):
        errors: list[Exception] = []

        def _append(n: int) -> None:
            try:
                for i in range(50):
                    self.db.event(f"t{n}-{i}")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_append, args=(k,)) for k in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [], "concurrent event() raised exceptions")


class TestDashboardLifecycle(unittest.TestCase):
    """start/update/unpin with DISCORD_DASHBOARD disabled to avoid real REST calls."""

    def setUp(self):
        self._patch = mock.patch.object(config, "DISCORD_DASHBOARD", False)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_start_noop_when_disabled(self):
        db = dash.DiscordDashboard()
        state = _task("executing")
        db.start(state, "starting")
        self.assertIsNone(db.message_id)   # never set because dashboard is off

    def test_update_noop_when_disabled(self):
        db = dash.DiscordDashboard()
        state = _task("executing")
        db.update(state, "executing", note="step done")
        self.assertIsNone(db.message_id)

    def test_unpin_noop_when_no_message_id(self):
        db = dash.DiscordDashboard()
        db.unpin()   # must not raise


class TestDashboardUpdateSetsMetadata(unittest.TestCase):
    """update() sets model/effort/events when Discord is enabled (REST mocked out)."""

    def setUp(self):
        self._p_dashboard = mock.patch.object(config, "DISCORD_DASHBOARD", True)
        self._p_edit = mock.patch("notifications.discord_bot.editMessage", return_value=True)
        self._p_create = mock.patch("notifications.discord_bot.createMessage", return_value="msg-1")
        self._p_pin = mock.patch("notifications.discord_bot.pinMessage", return_value=True)
        self._p_dashboard.start()
        self._p_edit.start()
        self._p_create.start()
        self._p_pin.start()

    def tearDown(self):
        self._p_pin.stop()
        self._p_create.stop()
        self._p_edit.stop()
        self._p_dashboard.stop()

    def test_effort_updated(self):
        db = dash.DiscordDashboard()
        db.message_id = "existing-msg"
        state = _task("executing")
        db.update(state, "executing", effort="high")
        self.assertEqual(db.effort, "high")

    def test_model_updated(self):
        db = dash.DiscordDashboard()
        db.message_id = "existing-msg"
        state = _task("executing")
        db.update(state, "executing", model="claude-opus-4-8")
        self.assertEqual(db.model, "claude-opus-4-8")

    def test_note_added_to_events(self):
        db = dash.DiscordDashboard()
        db.message_id = "existing-msg"
        state = _task("executing")
        db.update(state, "executing", note="subtask done")
        snap = db._eventsSnapshot()
        self.assertTrue(any("subtask done" in e for e in snap))


# ---------------------------------------------------------------------------
# command_bot – handleCommand
# ---------------------------------------------------------------------------

class TestHandleCommand(unittest.TestCase):
    def test_non_command_returns_empty(self):
        result = command_bot.handleCommand("hello there")
        self.assertEqual(result, "")

    def test_non_bang_returns_empty(self):
        result = command_bot.handleCommand("status")
        self.assertEqual(result, "")

    def test_no_task_returns_no_task_message(self):
        with mock.patch.object(commands, "resolveTargetTask", return_value=None):
            result = command_bot.handleCommand("!status")
        self.assertEqual(result, commands.NO_TASK)

    def test_valid_command_delegates_to_apply_command(self):
        state = _task("executing")
        fake_reply = "current status: executing"
        with mock.patch.object(commands, "resolveTargetTask", return_value=state), \
             mock.patch.object(commands, "applyCommand", return_value=fake_reply):
            result = command_bot.handleCommand("!status")
        self.assertEqual(result, fake_reply)

    def test_help_command_returns_text(self):
        state = _task("executing")
        with mock.patch.object(commands, "resolveTargetTask", return_value=state):
            result = command_bot.handleCommand("!help")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_unknown_command_returns_message(self):
        state = _task("executing")
        with mock.patch.object(commands, "resolveTargetTask", return_value=state):
            result = command_bot.handleCommand("!zzznonsense")
        # unknown commands should be handled gracefully (not raise)
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
