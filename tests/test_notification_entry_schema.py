"""Acceptance test: notification entry schema v2 — real-time update support.

Verifies the refactored schema that adds entry_id (unique identity) and
seq (monotonic ordering integer) to every notification entry, enabling
idempotent real-time patching and correct cross-second ordering.
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
    SCHEMA_VERSION,
    VALID_KINDS,
    makeEntry,
    validate,
    isValid,
)
from state.task import TaskState


# ---------------------------------------------------------------------------
# Schema constants
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
# isValid convenience wrapper
# ---------------------------------------------------------------------------

class TestIsValid(unittest.TestCase):
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
# Integration: TaskState.addNotification
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


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(__import__(__name__))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
