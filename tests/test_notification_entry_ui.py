"""Entry API and UI utility contracts for the 9TO5 notification system (st-006 / st-061).

Covers:
  - Contract 3: NotificationEntry structural contract (at/kind/detail keys required)
  - Contract 7: notifications.entry.makeEntry API
  - Contract 8: notifications.entry.validate / isValid API
  - Contract 9: VALID_KINDS vocabulary
  - Contract 11: discord_bot UI utilities: progressBar / subtaskTracker / formatVerdict
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import notifications.discord_bot as d
from notifications.entry import VALID_KINDS, makeEntry, isValid, validate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _notification_entry(kind: str = "replan", detail: str = "replanned") -> dict:
    """Return a well-formed notification entry (Gap 5: at/kind/detail required)."""
    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Contract 3: Notification entry structural contract (Gap 5)
# ---------------------------------------------------------------------------

class TestNotificationEntryContract(unittest.TestCase):
    """Notification entries written to state.data['notifications'] must have at/kind/detail."""

    def test_well_formed_entry_has_required_keys(self):
        entry = _notification_entry("replan", "subtask count changed")
        self.assertIn("at", entry)
        self.assertIn("kind", entry)
        self.assertIn("detail", entry)

    def test_at_is_iso8601(self):
        entry = _notification_entry()
        parsed = datetime.fromisoformat(entry["at"])
        self.assertIsNotNone(parsed)

    def test_kind_string_non_empty(self):
        entry = _notification_entry("adversary", "challenged st-002")
        self.assertIsInstance(entry["kind"], str)
        self.assertGreater(len(entry["kind"]), 0)

    def test_dashboard_counts_replan_from_notifications(self):
        """dashboard.py:111 counts n.get('kind') == 'replan'; must work with schema."""
        notifications = [
            _notification_entry("replan", "added 2 subtasks"),
            _notification_entry("subtask_done", "st-001 complete"),
            _notification_entry("replan", "removed 1 subtask"),
        ]
        replans = sum(1 for n in notifications if n.get("kind") == "replan")
        self.assertEqual(replans, 2)


# ---------------------------------------------------------------------------
# Contract 7: notifications.entry.makeEntry API (st-061)
# ---------------------------------------------------------------------------

class TestMakeEntryAPI(unittest.TestCase):
    """makeEntry must produce well-formed dicts and raise on invalid inputs."""

    def test_happy_path_returns_required_keys(self):
        entry = makeEntry("replan", "added 2 subtasks")
        self.assertIn("at", entry)
        self.assertIn("kind", entry)
        self.assertIn("detail", entry)

    def test_kind_and_detail_preserved(self):
        entry = makeEntry("blocked", "needs human input")
        self.assertEqual(entry["kind"], "blocked")
        self.assertEqual(entry["detail"], "needs human input")

    def test_at_is_parseable_iso8601(self):
        entry = makeEntry("complete", "all done")
        parsed = datetime.fromisoformat(entry["at"])
        self.assertIsNotNone(parsed)

    def test_extra_kwargs_included(self):
        entry = makeEntry("replan", "extra fields test", subtask_id="st-007", attempt=2)
        self.assertEqual(entry["subtask_id"], "st-007")
        self.assertEqual(entry["attempt"], 2)

    def test_extra_kwargs_do_not_clobber_required_fields(self):
        # Passing 'at' as an extra kwarg must NOT overwrite the validated timestamp.
        entry = makeEntry("replan", "detail text", at="1970-01-01T00:00:00+00:00")
        self.assertNotEqual(entry["at"], "1970-01-01T00:00:00+00:00")

    def test_empty_kind_raises_value_error(self):
        with self.assertRaises(ValueError):
            makeEntry("", "some detail")

    def test_non_string_kind_raises_value_error(self):
        with self.assertRaises(ValueError):
            makeEntry(42, "some detail")  # type: ignore[arg-type]

    def test_non_string_detail_raises_type_error(self):
        with self.assertRaises(TypeError):
            makeEntry("replan", 99)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Contract 8: notifications.entry.validate / isValid API (st-061)
# ---------------------------------------------------------------------------

class TestValidateAPI(unittest.TestCase):
    """validate() must return a list of error strings; isValid() is True iff validate() == []."""

    def test_valid_entry_returns_empty_errors(self):
        entry = makeEntry("subtask_done", "st-001 done")
        self.assertEqual(validate(entry), [])

    def test_is_valid_true_for_good_entry(self):
        entry = makeEntry("complete", "task finished")
        self.assertTrue(isValid(entry))

    def test_missing_at_reported(self):
        entry = {"kind": "replan", "detail": "ok"}
        errors = validate(entry)
        self.assertTrue(any("at" in e for e in errors))

    def test_missing_kind_reported(self):
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "detail": "ok"}
        errors = validate(entry)
        self.assertTrue(any("kind" in e for e in errors))

    def test_missing_detail_reported(self):
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "replan"}
        errors = validate(entry)
        self.assertTrue(any("detail" in e for e in errors))

    def test_non_dict_returns_type_error(self):
        errors = validate("not a dict")
        self.assertEqual(len(errors), 1)
        self.assertIn("dict", errors[0])

    def test_invalid_at_format_reported(self):
        entry = {"at": "not-a-date", "kind": "replan", "detail": "ok"}
        errors = validate(entry)
        self.assertTrue(any("at" in e for e in errors))

    def test_empty_kind_reported(self):
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "", "detail": "ok"}
        errors = validate(entry)
        self.assertTrue(any("kind" in e for e in errors))

    def test_non_str_detail_reported(self):
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "replan", "detail": 42}
        errors = validate(entry)
        self.assertTrue(any("detail" in e for e in errors))

    def test_is_valid_false_for_missing_key(self):
        self.assertFalse(isValid({"kind": "replan", "detail": "ok"}))


# ---------------------------------------------------------------------------
# Contract 9: VALID_KINDS vocabulary (st-061)
# ---------------------------------------------------------------------------

class TestValidKindsVocabulary(unittest.TestCase):
    def test_valid_kinds_is_frozenset(self):
        self.assertIsInstance(VALID_KINDS, frozenset)

    def test_core_kinds_present(self):
        for kind in ("replan", "complete", "aborted", "subtask_done", "subtask_failed", "blocked"):
            self.assertIn(kind, VALID_KINDS)

    def test_kinds_are_all_strings(self):
        self.assertTrue(all(isinstance(k, str) for k in VALID_KINDS))

    def test_no_empty_kind_in_vocabulary(self):
        self.assertNotIn("", VALID_KINDS)


# ---------------------------------------------------------------------------
# Contract 11: discord_bot UI utilities (st-061)
# ---------------------------------------------------------------------------

class TestProgressBar(unittest.TestCase):
    def test_zero_total_no_division_error(self):
        result = d.progressBar(0, 0)
        self.assertIn("%", result)

    def test_full_completion_shows_100(self):
        result = d.progressBar(10, 10)
        self.assertIn("100%", result)

    def test_zero_done_shows_0_percent(self):
        result = d.progressBar(0, 10)
        self.assertIn("0%", result)

    def test_done_exceeds_total_clamped(self):
        result = d.progressBar(15, 10)
        self.assertIn("100%", result)

    def test_returns_string(self):
        self.assertIsInstance(d.progressBar(3, 7), str)


class TestSubtaskTracker(unittest.TestCase):
    def test_all_pending_shows_no_pass_rate(self):
        subtasks = [{"status": "pending"} for _ in range(4)]
        result = d.subtaskTracker(subtasks)
        self.assertNotIn("pass", result)

    def test_pass_rate_computed_correctly(self):
        subtasks = [
            {"status": "done"},
            {"status": "done"},
            {"status": "failed"},
        ]
        result = d.subtaskTracker(subtasks)
        # 2 done out of 3 countable → 67%
        self.assertIn("67%", result)

    def test_empty_subtasks_no_error(self):
        result = d.subtaskTracker([])
        self.assertIsInstance(result, str)

    def test_all_done_shows_100_pass(self):
        subtasks = [{"status": "done"} for _ in range(5)]
        result = d.subtaskTracker(subtasks)
        self.assertIn("100%", result)


class TestFormatVerdict(unittest.TestCase):
    # icon prefix is '' when app emojis are not provisioned (headless) -> clean text labels.
    def test_approved_verdict(self):
        self.assertEqual(d.formatVerdict("approved"), "APPROVED")

    def test_challenged_verdict(self):
        self.assertEqual(d.formatVerdict("challenged"), "CHALLENGED")

    def test_unknown_verdict(self):
        self.assertEqual(d.formatVerdict("maybe"), "UNKNOWN")

    def test_none_verdict(self):
        self.assertEqual(d.formatVerdict(None), "UNKNOWN")

    def test_case_insensitive(self):
        self.assertEqual(d.formatVerdict("APPROVED"), "APPROVED")
        self.assertEqual(d.formatVerdict("Rejected"), "CHALLENGED")
