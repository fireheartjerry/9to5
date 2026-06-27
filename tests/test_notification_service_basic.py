"""Behavioral unit tests for notification service – basic UI-kit and embed builders.

Covers notifications/discord_bot.py:
  - UI kit: progressBar, subtaskTracker, statusColor, relTime, formatVerdict, _goalSummary
  - Embed builders: planningStartEmbed, adversaryTriggeredEmbed, blockedEmbed,
    abortedEmbed, subtaskFailedEmbed

Design constraints:
  - No real network calls (all Discord REST mocked).
  - No real Discord.py imports required (tested pure-Python paths only).
  - Tests cover happy path, edge cases, and error/invalid-input scenarios.
  - Behavioral scenarios are deterministic; no timing or ordering flakiness.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

import notifications.discord_bot as d


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
        result = d.subtaskTracker(subtasks)   # clean fallback (no app emoji provisioned in tests)
        self.assertIn("2 done", result)
        self.assertIn("1 active", result)
        self.assertIn("1 failed", result)
        self.assertIn("1 pending", result)

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
            self.assertIn("APPROVED", d.formatVerdict(v), msg=v)

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
        self.assertEqual(embed["title"], "Plan Ready")
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
        self.assertIn("Verify cmd", field_names)

    def test_none_verify_result_handled(self):
        embed = d.subtaskFailedEmbed("st-003", "title", None, 1)
        # None verify_result falls back to {} — "Verify cmd" field still present with default
        verify_val = next(f["value"] for f in embed["fields"] if f["name"] == "Verify cmd")
        self.assertIsInstance(verify_val, str)


if __name__ == "__main__":
    unittest.main()
