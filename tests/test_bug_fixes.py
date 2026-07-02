"""Bug-fix regression suite for st-072.

Covers three verified bugs:
  1. test_compute: GPU-detection mock missing — default_trainer returned a callable
     on GPU hosts instead of None.
  2. notification bus: emit() iterated _surfaces while the lock was held, blocking
     surfaces that re-register during emit; snapshot-then-release pattern fixes it.
  3. notification entry: makeEntry() lacked entry_id / seq fields required by the
     updated schema (REQUIRED_KEYS), so validate() would report errors on fresh entries.

Run directly: ``python tests/test_bug_fixes.py``  (expects exit 0).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


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
# Bug 2: NotificationBus thread safety — emit uses snapshot, not live list
# ---------------------------------------------------------------------------

class TestNotificationBusThreadSafety(unittest.TestCase):
    """emit() must snapshot _surfaces before iterating to avoid lock re-entrance."""

    def setUp(self):
        from notifications.bus import NotificationBus
        self.bus = NotificationBus()

    def test_emit_delivers_to_all_registered_surfaces(self):
        received = []

        class _Surf:
            def handle(self, event_type, payload):
                received.append((event_type, payload))

        s1, s2 = _Surf(), _Surf()
        self.bus.register(s1)
        self.bus.register(s2)
        self.bus.emit("test_event", {"x": 1})
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0], ("test_event", {"x": 1}))

    def test_surface_count_property(self):
        class _Surf:
            def handle(self, et, p): pass

        self.assertEqual(self.bus.surface_count, 0)
        self.bus.register(_Surf())
        self.assertEqual(self.bus.surface_count, 1)

    def test_emit_suppresses_surface_exception(self):
        class _BrokenSurf:
            def handle(self, et, p):
                raise RuntimeError("broken surface")

        class _GoodSurf:
            def __init__(self): self.called = False
            def handle(self, et, p): self.called = True

        good = _GoodSurf()
        self.bus.register(_BrokenSurf())
        self.bus.register(good)
        self.bus.emit("e", {})
        self.assertTrue(good.called, "good surface must receive event even if prior surface raised")

    def test_register_is_thread_safe(self):
        import threading

        class _Surf:
            def handle(self, et, p): pass

        threads = [threading.Thread(target=lambda: self.bus.register(_Surf()))
                   for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self.bus.surface_count, 20)


# ---------------------------------------------------------------------------
# Bug 3: makeEntry produces entries that pass validate() (entry_id + seq present)
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
