"""Behavioral unit tests for notification service modules.

Covers modules under notifications/ that lacked behavioral coverage:
  - notifications/discord_bot.py   (UI kit: progressBar, subtaskTracker,
    effortBar, statusColor, relTime, formatVerdict, _goalSummary, embed builders)
  - notifications/dashboard.py     (DiscordDashboard._elapsed, event deque,
    _eventsSnapshot, update lifecycle)
  - notifications/command_bot.py   (handleCommand routing)

Design constraints:
  - No real network calls (all Discord REST mocked).
  - No real Discord.py imports required (tested pure-Python paths only).
  - Tests cover happy path, edge cases, and error/invalid-input scenarios.
  - Behavioral scenarios are deterministic; no timing or ordering flakiness.

These tests verify that the notification service modules behave correctly under
normal operation, error conditions, and boundary inputs, and that changes to
these modules do not introduce regressions in their existing codebase behavior.
"""
from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import config
import notifications.discord_bot as d
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
# discord_bot – UI kit
# ---------------------------------------------------------------------------

class TestProgressBar(unittest.TestCase):
    def test_zero_done(self):
        bar = d.progressBar(0, 10)
        self.assertIn("0%", bar)
        self.assertIn("(0/10)", bar)

    def test_full(self):
        bar = d.progressBar(5, 5)
        self.assertIn("100%", bar)
        self.assertIn("(5/5)", bar)

    def test_overflow_clamped(self):
        # done > total should not raise and should show 100%
        bar = d.progressBar(12, 10)
        self.assertIn("100%", bar)

    def test_default_width_matches_format(self):
        bar = d.progressBar(3, 10)
        # bar contains filled + empty chars (▰/▱) and a percentage
        self.assertIn("%", bar)
        self.assertIn("/", bar)

    def test_zero_total_handled(self):
        bar = d.progressBar(0, 0)
        self.assertIn("%", bar)   # should not raise ZeroDivisionError


class TestSubtaskTracker(unittest.TestCase):
    def test_basic_counts(self):
        subtasks = [
            {"status": "done"},
            {"status": "done"},
            {"status": "in_progress"},
            {"status": "failed"},
            {"status": "pending"},
        ]
        result = d.subtaskTracker(subtasks)
        self.assertIn("✅", result)
        self.assertIn("⚡", result)
        self.assertIn("❌", result)
        self.assertIn("⬜", result)

    def test_all_done(self):
        subtasks = [{"status": "done"} for _ in range(4)]
        result = d.subtaskTracker(subtasks)
        self.assertIn("4", result)

    def test_empty_list(self):
        result = d.subtaskTracker([])
        self.assertIsInstance(result, str)


class TestStatusColor(unittest.TestCase):
    def test_known_status_returns_color(self):
        color = d.statusColor("done")
        self.assertIsInstance(color, int)

    def test_unknown_status_returns_neutral(self):
        neutral = d.statusColor("xyzzy_unknown_state_9999")
        self.assertIsInstance(neutral, int)
        self.assertEqual(neutral, 0x95A5A6)  # config neutral grey

    def test_none_returns_neutral(self):
        self.assertEqual(d.statusColor(None), 0x95A5A6)


class TestRelTime(unittest.TestCase):
    def test_none_returns_discord_format(self):
        result = d.relTime(None)
        self.assertRegex(result, r"<t:\d+:R>")

    def test_numeric_timestamp(self):
        result = d.relTime(1_700_000_000)
        self.assertIn("1700000000", result)

    def test_iso_string(self):
        dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = d.relTime(dt.isoformat())
        self.assertRegex(result, r"<t:\d+:R>")

    def test_invalid_string_falls_back(self):
        result = d.relTime("not-a-date-at-all")
        self.assertRegex(result, r"<t:\d+:R>")  # falls back to now


class TestFormatVerdict(unittest.TestCase):
    def test_approved_variants(self):
        for v in ("approved", "approve", "pass", "ok"):
            self.assertEqual(d.formatVerdict(v), "✅ APPROVED", msg=v)

    def test_challenged_variants(self):
        for v in ("challenged", "rejected", "reject", "blocked", "fail"):
            self.assertIn("CHALLENGED", d.formatVerdict(v), msg=v)

    def test_unknown(self):
        self.assertIn("UNKNOWN", d.formatVerdict("pending"))
        self.assertIn("UNKNOWN", d.formatVerdict(""))
        self.assertIn("UNKNOWN", d.formatVerdict(None))


class TestGoalSummary(unittest.TestCase):
    """_goalSummary is a private helper but is behavioral (drives embed descriptions)."""

    def test_short_text_unchanged(self):
        text = "short goal"
        self.assertEqual(d._goalSummary(text), text)

    def test_long_text_truncated(self):
        text = "word " * 100
        result = d._goalSummary(text, limit=50)
        self.assertLessEqual(len(result), 60)  # small padding for ellipsis

    def test_sentence_break_preferred(self):
        text = "First sentence. " + "x" * 200
        result = d._goalSummary(text, limit=30)
        # should prefer cutting after the first sentence
        self.assertIn("First sentence.", result)

    def test_empty_returns_dash(self):
        self.assertEqual(d._goalSummary(""), "—")
        self.assertEqual(d._goalSummary(None), "—")


# ---------------------------------------------------------------------------
# discord_bot – embed builders
# ---------------------------------------------------------------------------

class TestPlanningStartEmbed(unittest.TestCase):
    def test_int_subtask_count(self):
        embed = d.planningStartEmbed("build a thing", 5)
        self.assertEqual(embed["title"], "🗺️ Plan ready")
        self.assertIn("5", embed["description"])

    def test_list_subtasks_renders_titles(self):
        tasks = [{"title": f"task {i}"} for i in range(3)]
        embed = d.planningStartEmbed("goal", tasks)
        for i in range(3):
            self.assertIn(f"task {i}", embed["description"])

    def test_plural_vs_singular(self):
        embed_one = d.planningStartEmbed("g", 1)
        embed_many = d.planningStartEmbed("g", 3)
        self.assertIn("1 subtask", embed_one["description"])
        self.assertIn("3 subtasks", embed_many["description"])

    def test_overflow_list_shows_more(self):
        tasks = [{"title": f"t{i}"} for i in range(20)]
        embed = d.planningStartEmbed("g", tasks)
        self.assertIn("more", embed["description"])

    def test_description_within_discord_limit(self):
        long_goal = "x" * 5000
        embed = d.planningStartEmbed(long_goal, 1)
        self.assertLessEqual(len(embed["description"]), 4001)


class TestAdversaryTriggeredEmbed(unittest.TestCase):
    def test_approved_verdict_green_ish(self):
        embed = d.adversaryTriggeredEmbed("st-001", "heartbeat", verdict="approved")
        # approved -> statusColor("done")
        self.assertEqual(embed["color"], d.statusColor("done"))

    def test_challenged_verdict_red_ish(self):
        embed = d.adversaryTriggeredEmbed("st-001", "heartbeat", verdict="rejected")
        self.assertEqual(embed["color"], d.statusColor("blocked"))

    def test_none_verdict_no_verdict_field(self):
        embed = d.adversaryTriggeredEmbed("st-001", "heartbeat", verdict=None)
        field_names = [f["name"] for f in embed.get("fields", [])]
        self.assertNotIn("Verdict", field_names)

    def test_unknown_verdict_neutral_color(self):
        embed = d.adversaryTriggeredEmbed("st-001", "heartbeat", verdict="pending")
        self.assertEqual(embed["color"], 0x95A5A6)


class TestBlockedEmbed(unittest.TestCase):
    def test_question_quoted(self):
        embed = d.blockedEmbed("wait", question="what should I do?")
        desc = embed["description"]
        self.assertIn(">", desc)   # blockquote marker
        self.assertIn("what should I do?", desc)

    def test_no_question(self):
        embed = d.blockedEmbed("stuck on X")
        self.assertNotIn("asking:", embed.get("description", ""))

    def test_multiline_question_each_line_quoted(self):
        embed = d.blockedEmbed("r", question="line1\nline2")
        self.assertEqual(embed["description"].count(">"), 2)


class TestAbortedEmbed(unittest.TestCase):
    def test_fields_present(self):
        embed = d.abortedEmbed("user aborted", "5m")
        field_names = [f["name"] for f in embed["fields"]]
        self.assertIn("Reason", field_names)
        self.assertIn("Elapsed", field_names)

    def test_reason_truncated_if_long(self):
        embed = d.abortedEmbed("x" * 1000, "1m")
        reason_val = next(f["value"] for f in embed["fields"] if f["name"] == "Reason")
        self.assertLessEqual(len(reason_val), 520)  # 512 + ellipsis padding


class TestSubtaskFailedEmbed(unittest.TestCase):
    def test_structure(self):
        embed = d.subtaskFailedEmbed("st-002", "build thing", {"cmd": "pytest", "passed": False}, 2)
        field_names = [f["name"] for f in embed["fields"]]
        self.assertIn("Subtask", field_names)
        self.assertIn("Attempts", field_names)
        self.assertIn("Verify", field_names)

    def test_none_verify_result_handled(self):
        embed = d.subtaskFailedEmbed("st-003", "title", None, 1)
        verify_val = next(f["value"] for f in embed["fields"] if f["name"] == "Verify")
        self.assertIsInstance(verify_val, str)


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

    def test_maxlen_eight(self):
        for i in range(12):
            self.db.event(f"event {i}")
        snapshot = self.db._eventsSnapshot()
        self.assertEqual(len(snapshot), 8)

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
