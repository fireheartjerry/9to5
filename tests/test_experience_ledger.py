"""Unit tests for the Experience Ledger (SIE Layer 0)."""
import os
import shutil
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from memory import experience


def _forceRmtree(path) -> None:
    """Best-effort temp cleanup that tolerates a SQLite handle Windows hasn't released yet
    (WAL/-shm sidecars) so a passing test never errors in teardown."""
    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:  # noqa: BLE001
            pass
    shutil.rmtree(path, onerror=_onerror)


class TestExperienceLedger(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        # Most tests pass db_path explicitly; patch the config default too for the
        # paths that read it (sinks / __main__).
        self._patch = mock.patch.object(config, "EXPERIENCE_DB_PATH", self.db)
        self._patch.start()
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()

    def tearDown(self):
        mock.patch.stopall()
        # Release the pooled SQLite connection before unlinking the temp db, or Windows
        # raises PermissionError (WinError 32: file in use) on the open inode.
        experience._reset_schema_cache()
        _forceRmtree(self.dir)

    # ---- schema + roundtrip -------------------------------------------
    def test_init_creates_schema_in_wal(self):
        experience.init(self.db)
        self.assertTrue(self.db.exists())
        # NOTE: `with sqlite3.connect(...)` does NOT close the connection (it only manages the
        # transaction), so it would leak a handle and fail the Windows tearDown unlink. Close it.
        c = sqlite3.connect(self.db)
        try:
            tables = {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            c.close()
        self.assertTrue({"runs", "subtasks", "eval_runs"}.issubset(tables))

    def test_record_run_and_fetch(self):
        ok = experience.record_run({"run_id": "r1", "task_id": "r1", "goal_raw": "g",
                                    "status": "executing", "started_at": "2026-06-22T09:00:00"},
                                   db_path=self.db)
        self.assertTrue(ok)
        runs = experience.fetch_runs(self.db)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["goal_raw"], "g")

    def test_pool_reuses_one_connection_per_thread(self):
        experience.close_pool()
        with experience._connect(self.db) as c1:
            pass
        with experience._connect(self.db) as c2:
            pass
        self.assertIs(c1, c2)                       # same connection object reused

    def test_reset_schema_cache_drops_pooled_connection(self):
        with experience._connect(self.db) as c1:
            pass
        experience._reset_schema_cache()            # simulates a delete+recreate test boundary
        with experience._connect(self.db) as c2:
            pass
        self.assertIsNot(c1, c2)                     # fresh connection after reset

    def test_pool_disabled_opens_per_call(self):
        with mock.patch.object(config, "EXPERIENCE_POOL", False):
            with experience._connect(self.db) as c1:
                pass
            with experience._connect(self.db) as c2:
                pass
        self.assertIsNot(c1, c2)                     # no reuse when pooling is off

    def test_failed_txn_evicts_connection(self):
        experience.close_pool()
        with experience._connect(self.db) as c1:
            pass
        try:
            with experience._connect(self.db) as c2:
                self.assertIs(c1, c2)
                raise RuntimeError("boom")           # rollback + evict
        except RuntimeError:
            pass
        with experience._connect(self.db) as c3:
            pass
        self.assertIsNot(c1, c3)                     # poisoned conn was replaced

    def test_run_upsert_is_idempotent(self):
        for status in ("executing", "executing", "done"):
            experience.record_run({"run_id": "r1", "task_id": "r1", "status": status},
                                  db_path=self.db)
        runs = experience.fetch_runs(self.db)
        self.assertEqual(len(runs), 1)              # one row, not three
        self.assertEqual(runs[0]["status"], "done")  # last write wins

    def test_record_subtask_and_gold_filter(self):
        # A clean first-pass success -> gold. A retried/failed one -> not gold.
        experience.record_subtask("r1", {
            "subtask_id": "st-001", "title": "good", "status": "done",
            "verify_result": {"passed": True}, "session": {"attempts": 1, "effort": "high"},
        }, db_path=self.db)
        experience.record_subtask("r1", {
            "subtask_id": "st-002", "title": "messy", "status": "done",
            "verify_result": {"passed": True}, "session": {"attempts": 3},
        }, db_path=self.db)
        experience.record_subtask("r1", {
            "subtask_id": "st-003", "title": "failed", "status": "failed",
            "verify_result": {"passed": False}, "session": {"attempts": 3},
        }, db_path=self.db)
        gold = experience.gold_examples(self.db)
        self.assertEqual([g["st_id"] for g in gold], ["st-001"])

    def test_subtask_upsert_coalesces_detail(self):
        # First sync: only a verify result. Second: an adversary verdict. Detail accrues.
        experience.record_subtask("r1", {"subtask_id": "st-001", "status": "done",
                                         "verify_result": {"passed": True}}, db_path=self.db)
        experience.record_subtask("r1", {"subtask_id": "st-001",
                                         "_adversary_verdict": "approved"}, db_path=self.db)
        rows = experience.fetch_subtasks("r1", db_path=self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verify_passed"], 1)            # preserved
        self.assertEqual(rows[0]["adversary_verdict"], "approved")  # added

    def test_disabled_flag_skips_writes(self):
        with mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", False):
            self.assertFalse(experience.record_run({"run_id": "r1"}, db_path=self.db))
        self.assertEqual(experience.counts(self.db)["runs"], 0)

    def test_eval_and_fitness_series(self):
        experience.record_eval({"fitness": 0.7}, db_path=self.db)
        experience.record_eval({"fitness": 0.8}, db_path=self.db)
        series = experience.fitness_series(db_path=self.db)
        self.assertEqual([p["score"]["fitness"] for p in series], [0.7, 0.8])  # oldest-first

    # ---- sync from TaskState lean shapes ------------------------------
    def test_sync_run_and_subtask_from_state_data(self):
        state_data = {
            "task_id": "t9",
            "meta": {"goal_raw": "improve", "status": "executing", "control_mode": "watch"},
            "plan": {"subtasks": [
                {"subtask_id": "st-001", "title": "a", "status": "done",
                 "verify": {"cmd": "pytest", "expect": "exit_zero"},
                 "verify_result": {"passed": True}, "session": {"attempts": 1}},
            ]},
            "adversary_reviews": [
                {"subtask_id": "st-001", "verdict": "approved", "at": "now"}],
        }
        experience.sync_run(state_data, db_path=self.db)
        experience.sync_subtask(state_data, state_data["plan"]["subtasks"][0], db_path=self.db)
        rows = experience.fetch_subtasks("t9", db_path=self.db)
        self.assertEqual(rows[0]["position"], 0)
        self.assertEqual(rows[0]["adversary_verdict"], "approved")
        self.assertEqual(rows[0]["verify_cmd"], "pytest")

    def test_record_failure_is_swallowed(self):
        # A bad db path (a directory) must not raise -- best-effort contract.
        ok = experience.record_run({"run_id": "r1"}, db_path=self.dir)  # dir, not a file
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
