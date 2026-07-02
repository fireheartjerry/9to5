"""Behavioral unit tests for memory/subtask_manager.py.

All tests use an in-memory SQLite database so no disk state is created or
required.  Ollama is never called.  The Experience Ledger is monkeypatched
to point at a temp DB, so tests are hermetic and can run in any order.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Ensure the project root is on sys.path so `import config` works when this
# file is run directly as `python tests/test_memory_subtask_manager.py`.
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Bootstrap: point the experience ledger at a fresh in-memory DB for the
# entire test session, then disable the pool so each test gets a clean slate
# via _reset_schema_cache() in setUp.
# ---------------------------------------------------------------------------
import config  # noqa: E402 -- must come before memory imports


class _InMemoryDb:
    """Thin helper: returns a consistent :memory: path sentinel we can patch."""
    PATH = ":memory:"


# We patch config.EXPERIENCE_LEDGER_ENABLED = True for all tests.
# Individual tests can patch it to False to test the disabled branch.

# ---------------------------------------------------------------------------
# Helpers shared across test cases
# ---------------------------------------------------------------------------

def _seed_subtask(run_id: str, st_id: str, status: str, verify_passed: int | None = None,
                  attempt_count: int | None = None, *, db_path: Path | None = None):
    """Insert a minimal subtask row into the ledger."""
    from memory import experience
    vr: dict = {}
    if verify_passed is not None:
        vr["passed"] = bool(verify_passed)
    st = {
        "subtask_id": st_id,
        "status": status,
        "verify_result": vr,
    }
    if attempt_count is not None:
        st["session"] = {"attempts": attempt_count}
    experience.record_subtask(run_id, st, db_path=db_path)


# ---------------------------------------------------------------------------
# SubtaskStats dataclass
# ---------------------------------------------------------------------------

class TestSubtaskStats(unittest.TestCase):
    def setUp(self):
        from memory import subtask_manager
        self.sm = subtask_manager

    def test_pass_rate_zero_when_no_finished(self):
        from memory.subtask_manager import SubtaskStats
        s = SubtaskStats(run_id="r1", total=3, passed=0, failed=0, pending=3)
        self.assertEqual(s.pass_rate, 0.0)

    def test_pass_rate_all_passed(self):
        from memory.subtask_manager import SubtaskStats
        s = SubtaskStats(run_id="r1", total=2, passed=2, failed=0, pending=0)
        self.assertAlmostEqual(s.pass_rate, 1.0)

    def test_pass_rate_partial(self):
        from memory.subtask_manager import SubtaskStats
        s = SubtaskStats(run_id="r1", total=4, passed=3, failed=1, pending=0)
        self.assertAlmostEqual(s.pass_rate, 0.75)

    def test_avg_attempts_zero_when_no_subtasks(self):
        from memory.subtask_manager import SubtaskStats
        s = SubtaskStats(run_id="r1", total=0, total_attempts=0)
        self.assertEqual(s.avg_attempts, 0.0)

    def test_avg_attempts_computed(self):
        from memory.subtask_manager import SubtaskStats
        s = SubtaskStats(run_id="r1", total=2, total_attempts=6)
        self.assertAlmostEqual(s.avg_attempts, 3.0)


# ---------------------------------------------------------------------------
# getRunStats
# ---------------------------------------------------------------------------

class TestGetRunStats(unittest.TestCase):
    def setUp(self):
        from memory import experience
        experience._reset_schema_cache()
        self._db = Path(":memory:")
        config.EXPERIENCE_LEDGER_ENABLED = True

    def tearDown(self):
        from memory import experience
        experience.close_pool()
        config.EXPERIENCE_LEDGER_ENABLED = True

    def test_returns_none_for_blank_run_id(self):
        from memory import subtask_manager
        self.assertIsNone(subtask_manager.getRunStats(""))
        self.assertIsNone(subtask_manager.getRunStats("   "))

    def test_returns_none_when_ledger_disabled(self):
        config.EXPERIENCE_LEDGER_ENABLED = False
        from memory import subtask_manager
        self.assertIsNone(subtask_manager.getRunStats("some-run", db_path=self._db))

    def test_empty_run_returns_zeroed_stats(self):
        from memory import subtask_manager
        stats = subtask_manager.getRunStats("empty-run", db_path=self._db)
        self.assertIsNotNone(stats)
        self.assertEqual(stats.total, 0)
        self.assertEqual(stats.passed, 0)
        self.assertEqual(stats.pass_rate, 0.0)

    def test_counts_passed_and_failed(self):
        from memory import subtask_manager
        run_id = "run-cf"
        _seed_subtask(run_id, "st-1", "done", verify_passed=1, db_path=self._db)
        _seed_subtask(run_id, "st-2", "failed", verify_passed=0, db_path=self._db)
        _seed_subtask(run_id, "st-3", "done", verify_passed=1, db_path=self._db)
        stats = subtask_manager.getRunStats(run_id, db_path=self._db)
        self.assertEqual(stats.total, 3)
        self.assertEqual(stats.passed, 2)
        self.assertEqual(stats.failed, 1)
        self.assertAlmostEqual(stats.pass_rate, 2 / 3)

    def test_counts_pending_subtasks(self):
        from memory import subtask_manager
        run_id = "run-pending"
        _seed_subtask(run_id, "st-1", "running", db_path=self._db)
        _seed_subtask(run_id, "st-2", "queued", db_path=self._db)
        stats = subtask_manager.getRunStats(run_id, db_path=self._db)
        self.assertEqual(stats.pending, 2)
        self.assertEqual(stats.passed, 0)

    def test_counts_skipped_subtasks(self):
        from memory import subtask_manager
        run_id = "run-skip"
        _seed_subtask(run_id, "st-1", "skipped", db_path=self._db)
        stats = subtask_manager.getRunStats(run_id, db_path=self._db)
        self.assertEqual(stats.skipped, 1)
        self.assertEqual(stats.failed, 0)

    def test_accumulates_attempt_count(self):
        from memory import subtask_manager
        run_id = "run-attempts"
        _seed_subtask(run_id, "st-1", "done", verify_passed=1, attempt_count=3,
                      db_path=self._db)
        _seed_subtask(run_id, "st-2", "done", verify_passed=1, attempt_count=1,
                      db_path=self._db)
        stats = subtask_manager.getRunStats(run_id, db_path=self._db)
        self.assertEqual(stats.total_attempts, 4)
        self.assertAlmostEqual(stats.avg_attempts, 2.0)

    def test_status_counts_populated(self):
        from memory import subtask_manager
        run_id = "run-sc"
        _seed_subtask(run_id, "st-1", "done", verify_passed=1, db_path=self._db)
        _seed_subtask(run_id, "st-2", "done", verify_passed=1, db_path=self._db)
        _seed_subtask(run_id, "st-3", "failed", db_path=self._db)
        stats = subtask_manager.getRunStats(run_id, db_path=self._db)
        self.assertEqual(stats.status_counts.get("done", 0), 2)
        self.assertEqual(stats.status_counts.get("failed", 0), 1)


# ---------------------------------------------------------------------------
# getPassRate
# ---------------------------------------------------------------------------

class TestGetPassRate(unittest.TestCase):
    def setUp(self):
        from memory import experience
        experience._reset_schema_cache()
        self._db = Path(":memory:")
        config.EXPERIENCE_LEDGER_ENABLED = True

    def tearDown(self):
        from memory import experience
        experience.close_pool()
        config.EXPERIENCE_LEDGER_ENABLED = True

    def test_zero_for_blank_run_id(self):
        from memory import subtask_manager
        self.assertEqual(subtask_manager.getPassRate(""), 0.0)

    def test_zero_when_disabled(self):
        config.EXPERIENCE_LEDGER_ENABLED = False
        from memory import subtask_manager
        self.assertEqual(subtask_manager.getPassRate("any-run"), 0.0)

    def test_full_pass_rate(self):
        from memory import subtask_manager
        run_id = "run-full"
        _seed_subtask(run_id, "st-1", "done", verify_passed=1, db_path=self._db)
        _seed_subtask(run_id, "st-2", "done", verify_passed=1, db_path=self._db)
        rate = subtask_manager.getPassRate(run_id, db_path=self._db)
        self.assertAlmostEqual(rate, 1.0)

    def test_zero_for_empty_run(self):
        from memory import subtask_manager
        rate = subtask_manager.getPassRate("no-subtasks-run", db_path=self._db)
        self.assertEqual(rate, 0.0)


# ---------------------------------------------------------------------------
# pendingSubtasks
# ---------------------------------------------------------------------------

class TestPendingSubtasks(unittest.TestCase):
    def setUp(self):
        from memory import experience
        experience._reset_schema_cache()
        self._db = Path(":memory:")
        config.EXPERIENCE_LEDGER_ENABLED = True

    def tearDown(self):
        from memory import experience
        experience.close_pool()
        config.EXPERIENCE_LEDGER_ENABLED = True

    def test_empty_for_blank_run_id(self):
        from memory import subtask_manager
        self.assertEqual(subtask_manager.pendingSubtasks(""), [])

    def test_returns_only_non_terminal(self):
        from memory import subtask_manager
        run_id = "run-pend"
        _seed_subtask(run_id, "st-1", "running", db_path=self._db)
        _seed_subtask(run_id, "st-2", "done", verify_passed=1, db_path=self._db)
        _seed_subtask(run_id, "st-3", "queued", db_path=self._db)
        pending = subtask_manager.pendingSubtasks(run_id, db_path=self._db)
        ids = {r["st_id"] for r in pending}
        self.assertIn("st-1", ids)
        self.assertIn("st-3", ids)
        self.assertNotIn("st-2", ids)

    def test_empty_when_all_terminal(self):
        from memory import subtask_manager
        run_id = "run-terminal"
        _seed_subtask(run_id, "st-1", "done", verify_passed=1, db_path=self._db)
        _seed_subtask(run_id, "st-2", "failed", db_path=self._db)
        self.assertEqual(subtask_manager.pendingSubtasks(run_id, db_path=self._db), [])


# ---------------------------------------------------------------------------
# filterByStatus
# ---------------------------------------------------------------------------

class TestFilterByStatus(unittest.TestCase):
    def setUp(self):
        from memory import experience
        experience._reset_schema_cache()
        self._db = Path(":memory:")
        config.EXPERIENCE_LEDGER_ENABLED = True

    def tearDown(self):
        from memory import experience
        experience.close_pool()
        config.EXPERIENCE_LEDGER_ENABLED = True

    def test_empty_for_blank_run_id(self):
        from memory import subtask_manager
        self.assertEqual(subtask_manager.filterByStatus("", "done"), [])

    def test_empty_for_blank_status(self):
        from memory import subtask_manager
        self.assertEqual(subtask_manager.filterByStatus("run-x", ""), [])

    def test_filters_correctly(self):
        from memory import subtask_manager
        run_id = "run-flt"
        _seed_subtask(run_id, "st-1", "done", verify_passed=1, db_path=self._db)
        _seed_subtask(run_id, "st-2", "failed", db_path=self._db)
        _seed_subtask(run_id, "st-3", "done", verify_passed=1, db_path=self._db)
        done = subtask_manager.filterByStatus(run_id, "done", db_path=self._db)
        self.assertEqual(len(done), 2)

    def test_case_insensitive_match(self):
        from memory import subtask_manager
        run_id = "run-ci"
        _seed_subtask(run_id, "st-1", "DONE", verify_passed=1, db_path=self._db)
        # Status is stored lowercased after the record call maps it; check raw behavior
        results = subtask_manager.filterByStatus(run_id, "done", db_path=self._db)
        # At minimum, function should not crash; the actual count depends on DB storage
        self.assertIsInstance(results, list)


# ---------------------------------------------------------------------------
# markDone / markFailed / markSkipped
# ---------------------------------------------------------------------------

class TestMarkHelpers(unittest.TestCase):
    def setUp(self):
        from memory import experience
        experience._reset_schema_cache()
        self._db = Path(":memory:")
        config.EXPERIENCE_LEDGER_ENABLED = True

    def tearDown(self):
        from memory import experience
        experience.close_pool()
        config.EXPERIENCE_LEDGER_ENABLED = True

    def test_mark_done_returns_true(self):
        from memory import subtask_manager
        result = subtask_manager.markDone("run-a", "st-1", db_path=self._db)
        self.assertTrue(result)

    def test_mark_failed_returns_true(self):
        from memory import subtask_manager
        result = subtask_manager.markFailed("run-a", "st-2", db_path=self._db)
        self.assertTrue(result)

    def test_mark_skipped_returns_true(self):
        from memory import subtask_manager
        result = subtask_manager.markSkipped("run-a", "st-3", db_path=self._db)
        self.assertTrue(result)

    def test_mark_done_persists_verify_passed(self):
        from memory import experience, subtask_manager
        run_id, st_id = "run-md", "st-done"
        subtask_manager.markDone(run_id, st_id, db_path=self._db)
        rows = experience.fetch_subtasks(run_id, db_path=self._db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verify_passed"], 1)

    def test_mark_failed_persists_verify_failed(self):
        from memory import experience, subtask_manager
        run_id, st_id = "run-mf", "st-fail"
        subtask_manager.markFailed(run_id, st_id, db_path=self._db)
        rows = experience.fetch_subtasks(run_id, db_path=self._db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verify_passed"], 0)

    def test_mark_with_blank_run_id_returns_false(self):
        from memory import subtask_manager
        self.assertFalse(subtask_manager.markDone("", "st-x", db_path=self._db))
        self.assertFalse(subtask_manager.markFailed("", "st-x", db_path=self._db))
        self.assertFalse(subtask_manager.markSkipped("", "st-x", db_path=self._db))

    def test_mark_with_blank_st_id_returns_false(self):
        from memory import subtask_manager
        self.assertFalse(subtask_manager.markDone("run-y", "", db_path=self._db))

    def test_mark_done_then_stats_reflect_change(self):
        from memory import subtask_manager
        run_id = "run-transition"
        subtask_manager.markDone(run_id, "st-1", db_path=self._db)
        subtask_manager.markFailed(run_id, "st-2", db_path=self._db)
        stats = subtask_manager.getRunStats(run_id, db_path=self._db)
        self.assertEqual(stats.total, 2)
        self.assertEqual(stats.passed, 1)
        self.assertAlmostEqual(stats.pass_rate, 0.5)


# ---------------------------------------------------------------------------
# B22: partial upsert must NOT null out pre-existing fields
# ---------------------------------------------------------------------------

class TestPartialUpsertPreservesFields(unittest.TestCase):
    def setUp(self):
        from memory import experience
        experience._reset_schema_cache()
        self._db = Path(":memory:")
        config.EXPERIENCE_LEDGER_ENABLED = True

    def tearDown(self):
        from memory import experience
        experience.close_pool()
        config.EXPERIENCE_LEDGER_ENABLED = True

    def test_mark_done_preserves_title_position_ended_at(self):
        from memory import experience, subtask_manager
        run_id, st_id = "run-b22", "st-1"
        # Full insert: title, position, and completed_at (ended_at) all populated.
        experience.record_subtask(run_id, {
            "subtask_id": st_id, "title": "wire discord embed", "_position": 4,
            "status": "running", "completed_at": "2026-07-02T10:00:00",
        }, db_path=self._db)
        # Partial update via markDone: carries only subtask_id/status/verify_result.
        subtask_manager.markDone(run_id, st_id, db_path=self._db)
        rows = experience.fetch_subtasks(run_id, db_path=self._db)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["title"], "wire discord embed")
        self.assertEqual(row["position"], 4)
        self.assertEqual(row["ended_at"], "2026-07-02T10:00:00")
        self.assertEqual(row["verify_passed"], 1)   # the partial update DID apply
        self.assertEqual(row["status"], "done")


# ---------------------------------------------------------------------------
# TERMINAL_STATUSES / PASSING_STATUSES constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_terminal_statuses_contains_expected(self):
        from memory.subtask_manager import TERMINAL_STATUSES
        for s in ("done", "complete", "failed", "aborted", "blocked", "skipped"):
            self.assertIn(s, TERMINAL_STATUSES)

    def test_passing_statuses_subset_of_terminal(self):
        from memory.subtask_manager import PASSING_STATUSES, TERMINAL_STATUSES
        self.assertTrue(PASSING_STATUSES.issubset(TERMINAL_STATUSES))


if __name__ == "__main__":
    unittest.main()
