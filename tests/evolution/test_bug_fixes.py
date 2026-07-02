"""Bug-fix regression suite for st-072.

Covers two verified bugs:
  1. test_compute: GPU-detection mock missing — default_trainer returned a callable
     on GPU hosts instead of None.
  2. notification entry: makeEntry() lacked entry_id / seq fields required by the
     updated schema (REQUIRED_KEYS), so validate() would report errors on fresh entries.

Run directly: ``python tests/test_bug_fixes.py``  (expects exit 0).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ---------------------------------------------------------------------------
# Bug 1: default_trainer returns None when GPU unavailable
# ---------------------------------------------------------------------------

class TestDefaultTrainerGpuGuard(unittest.TestCase):
    """default_trainer / default_dpo_trainer must return None when should_use_gpu() is False."""

    def test_none_when_gpu_unavailable(self):
        from learning import finetune
        with mock.patch("learning.compute.training_enabled", return_value=True), \
             mock.patch("learning.compute.should_use_gpu", return_value=False):
            self.assertIsNone(finetune.default_trainer())
            self.assertIsNone(finetune.default_dpo_trainer())

    def test_none_when_training_disabled(self):
        from learning import finetune
        with mock.patch("learning.compute.training_enabled", return_value=False):
            self.assertIsNone(finetune.default_trainer())
            self.assertIsNone(finetune.default_dpo_trainer())

    def test_callable_when_gpu_available(self):
        from learning import finetune
        with mock.patch("learning.compute.training_enabled", return_value=True), \
             mock.patch("learning.compute.should_use_gpu", return_value=True):
            self.assertIsNotNone(finetune.default_trainer())
            self.assertIsNotNone(finetune.default_dpo_trainer())


# ---------------------------------------------------------------------------
# Bug 2: makeEntry produces entries that pass validate() (entry_id + seq present)
# ---------------------------------------------------------------------------

class TestNotificationEntrySchema(unittest.TestCase):
    """makeEntry must produce entries that satisfy validate() with no errors."""

    def setUp(self):
        from notifications.entry import makeEntry, validate, isValid, REQUIRED_KEYS
        self.makeEntry = makeEntry
        self.validate = validate
        self.isValid = isValid
        self.REQUIRED_KEYS = REQUIRED_KEYS

    def test_fresh_entry_is_valid(self):
        e = self.makeEntry("task_started", "Task started OK")
        errors = self.validate(e)
        self.assertEqual(errors, [], f"validate() returned errors: {errors}")

    def test_required_keys_present(self):
        e = self.makeEntry("task_started", "detail")
        for key in self.REQUIRED_KEYS:
            self.assertIn(key, e, f"REQUIRED_KEY {key!r} missing from entry")

    def test_entry_id_is_nonempty_string(self):
        e = self.makeEntry("task_started", "detail")
        self.assertIsInstance(e["entry_id"], str)
        self.assertTrue(e["entry_id"])

    def test_seq_is_positive_int(self):
        e = self.makeEntry("task_started", "detail")
        self.assertIsInstance(e["seq"], int)
        self.assertGreater(e["seq"], 0)

    def test_seq_monotonically_increases(self):
        e1 = self.makeEntry("task_started", "first")
        e2 = self.makeEntry("task_started", "second")
        self.assertGreater(e2["seq"], e1["seq"])

    def test_conflicting_kwarg_dropped(self):
        import logging
        with self.assertLogs("notifications.entry", level=logging.WARNING):
            e = self.makeEntry("task_started", "detail", entry_id="bad_override")
        self.assertNotEqual(e["entry_id"], "bad_override",
                            "conflicting kwarg must not overwrite built-in field")

    def test_isValid_convenience_wrapper(self):
        e = self.makeEntry("task_done", "done")
        self.assertTrue(self.isValid(e))
