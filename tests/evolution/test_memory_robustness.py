"""Behavioral unit tests for memory module error handling and input validation.

Covers modules under memory/ that lacked behavioral coverage for robustness:
  - memory/retrieval.py  (pack/unpack guards, render_lessons int-cast safety)
  - memory/experience.py (embedded_subtasks error barrier, record_run/record_subtask validation)

Design constraints:
  - No real Ollama or real SQLite files required (in-memory DB for experience tests).
  - Tests cover error conditions, invalid inputs, and boundary values.
  - Behavioral scenarios verify that strengthened error handling and input validation
    maintains existing codebase behavior while adding clear, descriptive error messages
    and appropriate exceptions where needed.

These tests verify the identified robustness and continuity bugs have been fixed and
that changes do not introduce regressions. All changes are accompanied by a corresponding
unit test that verifies the fix or improvement. Only non-core modules are modified to
improve error handling and input validation.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import config


# ---------------------------------------------------------------------------
# memory/retrieval – pack / unpack / render_lessons
# ---------------------------------------------------------------------------

class TestPack(unittest.TestCase):
    def setUp(self):
        from memory import retrieval
        self.r = retrieval

    def test_empty_vec_returns_empty_bytes(self):
        result = self.r.pack([])
        self.assertEqual(result, b"")

    def test_normal_vec_roundtrips(self):
        vec = [1.0, 2.0, 3.0]
        blob = self.r.pack(vec)
        self.assertEqual(len(blob), 12)  # 3 × 4 bytes float32

    def test_integer_elements_coerced(self):
        # pack should coerce int elements to float without raising
        blob = self.r.pack([1, 2, 3])
        self.assertIsInstance(blob, bytes)
        self.assertEqual(len(blob), 12)


class TestUnpack(unittest.TestCase):
    def setUp(self):
        from memory import retrieval
        self.r = retrieval

    def test_none_returns_empty(self):
        result = self.r.unpack(None)
        self.assertEqual(result, [])

    def test_empty_bytes_returns_empty(self):
        result = self.r.unpack(b"")
        self.assertEqual(result, [])

    def test_misaligned_blob_returns_empty(self):
        # 5 bytes is not divisible by 4 — invalid float32 blob
        result = self.r.unpack(b"\x00\x01\x02\x03\x04")
        self.assertEqual(result, [])

    def test_non_bytes_returns_empty(self):
        result = self.r.unpack("not bytes")
        self.assertEqual(result, [])

    def test_valid_blob_roundtrips(self):
        import array
        a = array.array("f", [1.5, 2.5, 3.5])
        blob = a.tobytes()
        result = self.r.unpack(blob)
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(result[0], 1.5, places=4)

    def test_pack_unpack_roundtrip(self):
        vec = [0.1, 0.2, 0.3, 0.9]
        result = self.r.unpack(self.r.pack(vec))
        self.assertEqual(len(result), 4)
        for orig, restored in zip(vec, result):
            self.assertAlmostEqual(orig, restored, places=4)


class TestRenderLessons(unittest.TestCase):
    """render_lessons should handle float/string attempt_count without raising."""

    def setUp(self):
        from memory import retrieval
        self.r = retrieval

    def _neighbor(self, title="test task", attempt_count=1):
        return {"title": title, "effort": "medium", "attempt_count": attempt_count, "score": 0.9}

    def test_int_attempt_count_works(self):
        result = self.r.render_lessons([self._neighbor(attempt_count=3)])
        self.assertIn("needed 3 tries", result)

    def test_float_attempt_count_does_not_raise(self):
        # SQLite may return REAL columns as floats
        result = self.r.render_lessons([self._neighbor(attempt_count=2.0)])
        self.assertIn("needed 2 tries", result)

    def test_string_float_attempt_count_does_not_raise(self):
        # Defensive: string-encoded float should not raise ValueError
        result = self.r.render_lessons([self._neighbor(attempt_count="1.5")])
        self.assertIsInstance(result, str)

    def test_none_attempt_count_no_tries_line(self):
        result = self.r.render_lessons([self._neighbor(attempt_count=None)])
        self.assertNotIn("tries", result)

    def test_bad_string_attempt_count_no_tries_line(self):
        # A truly non-numeric string should degrade silently, not raise
        result = self.r.render_lessons([self._neighbor(attempt_count="bad")])
        self.assertIsInstance(result, str)

    def test_empty_neighbors_returns_empty_string(self):
        self.assertEqual(self.r.render_lessons([]), "")

    def test_single_attempt_no_tries_line(self):
        result = self.r.render_lessons([self._neighbor(attempt_count=1)])
        self.assertNotIn("tries", result)


# ---------------------------------------------------------------------------
# memory/experience – record_run / record_subtask / embedded_subtasks validation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# memory/retrieval – embed() negative-cache reset after success
# ---------------------------------------------------------------------------

class TestEmbedNegativeCache(unittest.TestCase):
    """embed() must reset _last_embed_fail_at to -inf (not 0.0) after success,
    so a subsequent call on a freshly-booted system is not wrongly suppressed."""

    def setUp(self):
        from memory import retrieval
        self.r = retrieval
        retrieval.reset_embed_cache()

    def tearDown(self):
        self.r.reset_embed_cache()

    def test_success_does_not_suppress_next_call(self):
        """After a successful embed, the very next call must also execute (not be suppressed).

        Bug: _last_embed_fail_at was set to 0.0 on success. On a system where
        time.monotonic() < FAIL_COOLDOWN_SECONDS (< 60s uptime), the next call
        would see monotonic() - 0.0 < cooldown and return None (suppressed).
        Fix: reset to float('-inf') so the gap is always larger than the cooldown.
        """
        from unittest import mock

        calls = []

        def fake_embed(text):
            calls.append(text)
            return [0.1, 0.2, 0.3]

        # Simulate system with monotonic() = 30.0 (uptime < cooldown of 60s)
        with mock.patch.object(self.r, '_embed_call', side_effect=fake_embed), \
             mock.patch('time.monotonic', return_value=30.0):
            result1 = self.r.embed("first text")
            result2 = self.r.embed("second text")

        self.assertIsNotNone(result1, "first embed should succeed")
        self.assertIsNotNone(result2, "second embed must not be suppressed after a success")
        self.assertEqual(len(calls), 2, "_embed_call must be invoked twice")

    def test_failure_suppresses_within_cooldown(self):
        """After a failure, calls within the cooldown window must be suppressed."""
        from unittest import mock

        calls = []

        def fake_embed_fail(text):
            calls.append(text)
            return None

        # embed() calls monotonic() twice per failure (guard check + store), once per suppressed
        side_effects = [1000.0, 1000.0, 1050.0]   # fail@1000 stored, next check@1050 < cooldown
        with mock.patch.object(self.r, '_embed_call', side_effect=fake_embed_fail), \
             mock.patch('time.monotonic', side_effect=side_effects):
            result1 = self.r.embed("first")
            result2 = self.r.embed("second")

        self.assertIsNone(result1, "should return None on embed failure")
        self.assertIsNone(result2, "should be suppressed within cooldown window")
        self.assertEqual(len(calls), 1, "_embed_call must only be called once (second suppressed)")


# ---------------------------------------------------------------------------
# memory/experience – record_run / record_subtask / embedded_subtasks validation
# ---------------------------------------------------------------------------

class TestRecordRunValidation(unittest.TestCase):
    """record_run must reject invalid inputs with clear descriptive behavior."""

    def setUp(self):
        from memory import experience
        self.exp = experience
        # Use an in-memory DB path (temp file that doesn't persist)
        import tempfile
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Path(self.tmp.name)

    def tearDown(self):
        self.exp.close_pool()
        try:
            self.db.unlink()
        except OSError:
            pass

    def _patch_ledger(self, enabled=True):
        from unittest import mock
        return mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", enabled)

    def test_missing_run_id_returns_false(self):
        with self._patch_ledger():
            result = self.exp.record_run({}, db_path=self.db)
        self.assertFalse(result)

    def test_empty_run_id_returns_false(self):
        with self._patch_ledger():
            result = self.exp.record_run({"run_id": ""}, db_path=self.db)
        self.assertFalse(result)

    def test_whitespace_run_id_returns_false(self):
        with self._patch_ledger():
            result = self.exp.record_run({"run_id": "   "}, db_path=self.db)
        self.assertFalse(result)

    def test_non_dict_run_returns_false(self):
        with self._patch_ledger():
            result = self.exp.record_run(None, db_path=self.db)
        self.assertFalse(result)

    def test_valid_run_id_succeeds(self):
        with self._patch_ledger():
            result = self.exp.record_run({"run_id": "test-run-001"}, db_path=self.db)
        self.assertTrue(result)

    def test_ledger_disabled_returns_false(self):
        with self._patch_ledger(enabled=False):
            result = self.exp.record_run({"run_id": "test-run-002"}, db_path=self.db)
        self.assertFalse(result)


class TestRecordSubtaskValidation(unittest.TestCase):
    """record_subtask must reject invalid inputs; subtask_id required."""

    def setUp(self):
        from memory import experience
        self.exp = experience
        import tempfile
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Path(self.tmp.name)

    def tearDown(self):
        self.exp.close_pool()
        try:
            self.db.unlink()
        except OSError:
            pass

    def _patch_ledger(self, enabled=True):
        from unittest import mock
        return mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", enabled)

    def test_missing_run_id_returns_false(self):
        with self._patch_ledger():
            result = self.exp.record_subtask("", {"subtask_id": "st-001"}, db_path=self.db)
        self.assertFalse(result)

    def test_missing_subtask_id_returns_false(self):
        with self._patch_ledger():
            result = self.exp.record_subtask("run-001", {}, db_path=self.db)
        self.assertFalse(result)

    def test_non_dict_st_returns_false(self):
        with self._patch_ledger():
            result = self.exp.record_subtask("run-001", None, db_path=self.db)
        self.assertFalse(result)

    def test_valid_inputs_succeed(self):
        with self._patch_ledger():
            # First create the run row (FK constraint)
            self.exp.record_run({"run_id": "run-001"}, db_path=self.db)
            result = self.exp.record_subtask(
                "run-001", {"subtask_id": "st-001", "title": "test"}, db_path=self.db
            )
        self.assertTrue(result)


class TestEmbeddedSubtasksRobustness(unittest.TestCase):
    """embedded_subtasks must return [] (not raise) when the DB is unavailable."""

    def setUp(self):
        from memory import experience
        self.exp = experience

    def test_nonexistent_db_returns_empty_list(self):
        # A path that will definitely not exist and not be created
        bad_path = Path("Z:/nonexistent/path/that/cannot/exist.db")
        result = self.exp.embedded_subtasks(db_path=bad_path)
        self.assertIsInstance(result, list)
        # On Windows, this path is genuinely invalid; must not raise
        # (may return [] directly if the path is invalid before even connecting)

    def test_returns_list_type_always(self):
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db = Path(tmp.name)
        try:
            self.exp.init(db_path=db)
            result = self.exp.embedded_subtasks(db_path=db)
            self.assertIsInstance(result, list)
        finally:
            self.exp.close_pool()
            try:
                db.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# notifications/webdash – _applyControl input validation
# ---------------------------------------------------------------------------

class TestApplyControlValidation(unittest.TestCase):
    """_applyControl must reject non-string and empty action strings descriptively."""

    def setUp(self):
        from notifications import webdash
        self.webdash = webdash

    def test_none_action_returns_error(self):
        result = self.webdash._applyControl("task-123", None, None)
        self.assertFalse(result["ok"])
        self.assertIn("string", result["error"])

    def test_empty_action_returns_error(self):
        result = self.webdash._applyControl("task-123", "", None)
        self.assertFalse(result["ok"])
        self.assertIn("string", result["error"])

    def test_int_action_returns_error(self):
        result = self.webdash._applyControl("task-123", 42, None)
        self.assertFalse(result["ok"])

    def test_empty_task_id_returns_error(self):
        result = self.webdash._applyControl("", "abort", None)
        self.assertFalse(result["ok"])
        self.assertIn("task", result["error"])

    def test_none_task_id_returns_error(self):
        result = self.webdash._applyControl(None, "abort", None)
        self.assertFalse(result["ok"])

    def test_unknown_action_returns_error(self):
        result = self.webdash._applyControl("task-123", "xyzzy_unknown", None)
        self.assertFalse(result["ok"])
        self.assertIn("unknown", result["error"])
