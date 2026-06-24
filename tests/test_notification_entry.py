"""Tests for the NotificationEntry schema (notifications/entry.py).

Validates that makeEntry produces well-formed entries and that validate()
catches malformed ones. Also covers integration with TaskState.addNotification.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from notifications.entry import (
    REQUIRED_KEYS,
    VALID_KINDS,
    makeEntry,
    validate,
)
from state.task import TaskState


# ---------------------------------------------------------------------------
# makeEntry
# ---------------------------------------------------------------------------

class TestMakeEntry(unittest.TestCase):
    def test_returns_all_required_keys(self):
        entry = makeEntry("replan", "added 2 subtasks")
        for key in REQUIRED_KEYS:
            self.assertIn(key, entry)

    def test_at_is_utc_iso8601(self):
        entry = makeEntry("replan", "detail")
        parsed = datetime.fromisoformat(entry["at"])
        # UTC offset must be +00:00
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    def test_at_has_second_precision(self):
        entry = makeEntry("complete", "done")
        # fromisoformat round-trips and no sub-second component
        at = entry["at"]
        self.assertNotIn(".", at)

    def test_kind_preserved(self):
        entry = makeEntry("subtask_failed", "st-001 verify failed")
        self.assertEqual(entry["kind"], "subtask_failed")

    def test_detail_preserved(self):
        entry = makeEntry("replan", "reason xyz")
        self.assertEqual(entry["detail"], "reason xyz")

    def test_extra_kwargs_included(self):
        entry = makeEntry("selfmod_gate", "reverted", reverted=True)
        self.assertIn("reverted", entry)
        self.assertTrue(entry["reverted"])

    def test_empty_kind_raises(self):
        with self.assertRaises(ValueError):
            makeEntry("", "detail")

    def test_empty_detail_allowed(self):
        entry = makeEntry("aborted", "")
        self.assertEqual(entry["detail"], "")

    def test_non_string_kind_raises(self):
        with self.assertRaises((ValueError, TypeError)):
            makeEntry(123, "detail")  # type: ignore[arg-type]

    def test_non_string_detail_raises(self):
        with self.assertRaises(TypeError):
            makeEntry("replan", None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

class TestValidate(unittest.TestCase):
    def test_valid_entry_returns_no_errors(self):
        entry = makeEntry("replan", "some reason")
        self.assertEqual(validate(entry), [])

    def test_missing_at_reported(self):
        entry = {"kind": "replan", "detail": "x"}
        errors = validate(entry)
        self.assertTrue(any("at" in e for e in errors))

    def test_missing_kind_reported(self):
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "detail": "x"}
        errors = validate(entry)
        self.assertTrue(any("kind" in e for e in errors))

    def test_missing_detail_reported(self):
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "replan"}
        errors = validate(entry)
        self.assertTrue(any("detail" in e for e in errors))

    def test_bad_at_format_reported(self):
        entry = {"at": "not-a-date", "kind": "replan", "detail": "x"}
        errors = validate(entry)
        self.assertTrue(any("at" in e for e in errors))

    def test_empty_kind_reported(self):
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "", "detail": "x"}
        errors = validate(entry)
        self.assertTrue(any("kind" in e for e in errors))

    def test_non_dict_entry_reported(self):
        errors = validate("not-a-dict")  # type: ignore[arg-type]
        self.assertTrue(len(errors) > 0)

    def test_non_string_detail_reported(self):
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": "replan", "detail": 42}
        errors = validate(entry)
        self.assertTrue(any("detail" in e for e in errors))


# ---------------------------------------------------------------------------
# VALID_KINDS coverage
# ---------------------------------------------------------------------------

class TestValidKinds(unittest.TestCase):
    def test_valid_kinds_is_nonempty_frozenset(self):
        self.assertIsInstance(VALID_KINDS, frozenset)
        self.assertGreater(len(VALID_KINDS), 0)

    def test_core_kinds_present(self):
        for kind in ("replan", "complete", "aborted", "subtask_failed"):
            self.assertIn(kind, VALID_KINDS)

    def test_all_valid_kinds_produce_valid_entries(self):
        for kind in VALID_KINDS:
            entry = makeEntry(kind, "detail")
            errors = validate(entry)
            self.assertEqual(errors, [], f"kind={kind!r} produced errors: {errors}")


# ---------------------------------------------------------------------------
# Integration: TaskState.addNotification
# ---------------------------------------------------------------------------

class TestTaskStateAddNotification(unittest.TestCase):
    def setUp(self):
        self.state = TaskState.create("test notification schema", 1.0)

    def test_addNotification_returns_valid_entry(self):
        rec = self.state.addNotification("replan", "replanned for test")
        errors = validate(rec)
        self.assertEqual(errors, [])

    def test_addNotification_appended_to_data(self):
        before = len(self.state.data["notifications"])
        self.state.addNotification("subtask_done", "st-001 done")
        self.assertEqual(len(self.state.data["notifications"]), before + 1)

    def test_addNotification_entry_matches_schema(self):
        rec = self.state.addNotification("architect_done", "arch.md")
        for key in REQUIRED_KEYS:
            self.assertIn(key, rec)
        self.assertEqual(rec["kind"], "architect_done")
        self.assertEqual(rec["detail"], "arch.md")

    def test_addNotification_extra_kwargs_preserved(self):
        rec = self.state.addNotification("selfmod_gate", "reverted", reverted=True)
        self.assertTrue(rec.get("reverted"))

    def test_multiple_notifications_independent(self):
        self.state.addNotification("replan", "first")
        self.state.addNotification("replan", "second")
        notifs = self.state.data["notifications"]
        details = [n["detail"] for n in notifs if n["kind"] == "replan"]
        self.assertIn("first", details)
        self.assertIn("second", details)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(__import__(__name__))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("Schema validation passed")
    else:
        sys.exit(1)
