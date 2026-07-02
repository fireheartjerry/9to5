"""Tests for the NotificationEntry schema (notifications/entry.py) — merged.

Validates that makeEntry produces well-formed entries and that validate()
catches malformed ones. Also covers schema v2 (entry_id, seq, schema_version),
and UI utility contracts for the 9TO5 notification system.

Includes:
  - Original entry tests (makeEntry, validate, VALID_KINDS, TaskState.addNotification)
  - Schema v2 acceptance tests (entry_id, seq, schema_version)
  - Entry API and UI utility contracts (st-006 / st-061)
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import notifications.discord_bot as d
from notifications.entry import (
    REQUIRED_KEYS,
    SCHEMA_VERSION,
    VALID_KINDS,
    isValid,
    makeEntry,
    validate,
)
from state.task import TaskState


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
# Integration: TaskState.addNotification (original)
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


# ---------------------------------------------------------------------------
# Schema v2 constants
# ---------------------------------------------------------------------------

class TestSchemaConstants(unittest.TestCase):
    def test_required_keys_includes_entry_id(self):
        self.assertIn("entry_id", REQUIRED_KEYS)

    def test_required_keys_includes_seq(self):
        self.assertIn("seq", REQUIRED_KEYS)

    def test_required_keys_includes_legacy_fields(self):
        for key in ("at", "kind", "detail"):
            self.assertIn(key, REQUIRED_KEYS)

    def test_schema_version_is_string(self):
        self.assertIsInstance(SCHEMA_VERSION, str)
        self.assertTrue(SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# entry_id — unique identity for real-time patch targeting
# ---------------------------------------------------------------------------

class TestEntryId(unittest.TestCase):
    def test_entry_id_present(self):
        entry = makeEntry("replan", "detail")
        self.assertIn("entry_id", entry)

    def test_entry_id_is_nonempty_string(self):
        entry = makeEntry("replan", "detail")
        self.assertIsInstance(entry["entry_id"], str)
        self.assertTrue(entry["entry_id"])

    def test_entry_id_unique_across_entries(self):
        ids = [makeEntry("replan", "x")["entry_id"] for _ in range(20)]
        self.assertEqual(len(set(ids)), 20)

    def test_entry_id_uuid_format(self):
        import uuid
        entry = makeEntry("complete", "done")
        # should parse as UUID without raising
        parsed = uuid.UUID(entry["entry_id"])
        self.assertEqual(str(parsed), entry["entry_id"])


# ---------------------------------------------------------------------------
# seq — monotonic ordering for real-time replay
# ---------------------------------------------------------------------------

class TestSeq(unittest.TestCase):
    def test_seq_present(self):
        entry = makeEntry("replan", "detail")
        self.assertIn("seq", entry)

    def test_seq_is_positive_int(self):
        entry = makeEntry("replan", "detail")
        self.assertIsInstance(entry["seq"], int)
        self.assertGreater(entry["seq"], 0)

    def test_seq_monotonically_increasing(self):
        entries = [makeEntry("subtask_done", f"st-{i:03d}") for i in range(10)]
        seqs = [e["seq"] for e in entries]
        for a, b in zip(seqs, seqs[1:]):
            self.assertLess(a, b)

    def test_seq_ordering_survives_same_timestamp(self):
        # Two entries may share the same 'at' second; seq must still differentiate.
        a = makeEntry("replan", "first")
        b = makeEntry("replan", "second")
        self.assertNotEqual(a["seq"], b["seq"])
        self.assertLess(a["seq"], b["seq"])


# ---------------------------------------------------------------------------
# schema_version
# ---------------------------------------------------------------------------

class TestSchemaVersionField(unittest.TestCase):
    def test_schema_version_in_entry(self):
        entry = makeEntry("replan", "detail")
        self.assertIn("schema_version", entry)
        self.assertEqual(entry["schema_version"], SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# validate — data integrity checks for new fields
# ---------------------------------------------------------------------------

class TestValidateNewFields(unittest.TestCase):
    def _base(self) -> dict:
        return makeEntry("replan", "x").copy()

    def test_valid_entry_no_errors(self):
        self.assertEqual(validate(self._base()), [])

    def test_missing_entry_id_reported(self):
        entry = self._base()
        del entry["entry_id"]
        errors = validate(entry)
        self.assertTrue(any("entry_id" in e for e in errors))

    def test_empty_entry_id_reported(self):
        entry = self._base()
        entry["entry_id"] = ""
        errors = validate(entry)
        self.assertTrue(any("entry_id" in e for e in errors))

    def test_missing_seq_reported(self):
        entry = self._base()
        del entry["seq"]
        errors = validate(entry)
        self.assertTrue(any("seq" in e for e in errors))

    def test_non_int_seq_reported(self):
        entry = self._base()
        entry["seq"] = "not-an-int"
        errors = validate(entry)
        self.assertTrue(any("seq" in e for e in errors))

    def test_float_seq_reported(self):
        entry = self._base()
        entry["seq"] = 1.5
        errors = validate(entry)
        self.assertTrue(any("seq" in e for e in errors))

    def test_legacy_entry_missing_new_fields_fails(self):
        # Entries created before the v2 schema lack entry_id and seq.
        legacy = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": "replan",
            "detail": "old entry",
        }
        errors = validate(legacy)
        missing = [e for e in errors if "entry_id" in e or "seq" in e]
        self.assertTrue(len(missing) >= 2)


# ---------------------------------------------------------------------------
# isValid convenience wrapper (schema v2)
# ---------------------------------------------------------------------------

class TestIsValidSchemaV2(unittest.TestCase):
    def test_valid_entry_returns_true(self):
        self.assertTrue(isValid(makeEntry("complete", "done")))

    def test_invalid_entry_returns_false(self):
        self.assertFalse(isValid({"kind": "replan", "detail": "x"}))


# ---------------------------------------------------------------------------
# makeEntry — backward-compatible existing behaviour still works
# ---------------------------------------------------------------------------

class TestMakeEntryBackcompat(unittest.TestCase):
    def test_all_required_keys_present(self):
        entry = makeEntry("replan", "added 2 subtasks")
        for key in REQUIRED_KEYS:
            self.assertIn(key, entry)

    def test_at_is_utc_iso8601(self):
        entry = makeEntry("replan", "detail")
        parsed = datetime.fromisoformat(entry["at"])
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    def test_at_second_precision(self):
        entry = makeEntry("complete", "done")
        self.assertNotIn(".", entry["at"])

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

    def test_non_string_kind_raises(self):
        with self.assertRaises((ValueError, TypeError)):
            makeEntry(123, "detail")  # type: ignore[arg-type]

    def test_non_string_detail_raises(self):
        with self.assertRaises(TypeError):
            makeEntry("replan", None)  # type: ignore[arg-type]

    def test_all_valid_kinds_produce_valid_entries(self):
        for kind in VALID_KINDS:
            entry = makeEntry(kind, "detail")
            errors = validate(entry)
            self.assertEqual(errors, [], f"kind={kind!r} produced errors: {errors}")


# ---------------------------------------------------------------------------
# Integration: TaskState.addNotification (schema v2)
# ---------------------------------------------------------------------------

class TestTaskStateIntegration(unittest.TestCase):
    def setUp(self):
        self.state = TaskState.create("test entry schema v2", 1.0)

    def test_addNotification_returns_valid_entry(self):
        rec = self.state.addNotification("replan", "replanned for test")
        self.assertEqual(validate(rec), [])

    def test_addNotification_has_entry_id(self):
        rec = self.state.addNotification("replan", "test")
        self.assertIn("entry_id", rec)
        self.assertTrue(rec["entry_id"])

    def test_addNotification_has_seq(self):
        rec = self.state.addNotification("replan", "test")
        self.assertIsInstance(rec["seq"], int)
        self.assertGreater(rec["seq"], 0)

    def test_addNotification_entry_ids_unique(self):
        recs = [self.state.addNotification("replan", f"n{i}") for i in range(5)]
        ids = [r["entry_id"] for r in recs]
        self.assertEqual(len(set(ids)), 5)

    def test_addNotification_seq_ordered(self):
        recs = [self.state.addNotification("subtask_done", f"st-{i:03d}") for i in range(5)]
        seqs = [r["seq"] for r in recs]
        for a, b in zip(seqs, seqs[1:]):
            self.assertLess(a, b)

    def test_addNotification_appended_to_data(self):
        before = len(self.state.data["notifications"])
        self.state.addNotification("subtask_done", "st-001 done")
        self.assertEqual(len(self.state.data["notifications"]), before + 1)


# ---------------------------------------------------------------------------
# Contract 3: Notification entry structural contract (Gap 5) — ui contracts
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
# Contract 7: notifications.entry.makeEntry API (st-061) — ui contracts
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

class TestProgressBarUI(unittest.TestCase):
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


class TestSubtaskTrackerUI(unittest.TestCase):
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


class TestFormatVerdictUI(unittest.TestCase):
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
