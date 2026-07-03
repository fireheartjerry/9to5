"""Unit tests for the Self-Improvement Orchestrator auto-runner (learning/sie.py)."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import sie
from memory import experience, retrieval


class TestSieMaintenance(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "CONTROL_DIR", self.dir / "control").start()
        mock.patch.object(config, "VAULT_DISK_ROOT", self.dir / "vault").start()
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()
        mock.patch.object(config, "SIE_KILL_SWITCH", False).start()
        # Keep maintenance fully offline + fast: no embedder, and an empty eval suite so
        # the verify runner doesn't spawn real subprocesses during the unit test.
        mock.patch.object(retrieval, "_embed_call", return_value=None).start()
        mock.patch.object(config, "EVAL_SUITE_DIR", self.dir / "nosuite").start()
        # Never let the auto-runner spawn real self-play runs or shell out during unit tests.
        mock.patch.object(config, "SELFPLAY_ENABLED", False).start()
        mock.patch.object(config, "SIE_BOOTSTRAP", False).start()
        retrieval.reset_embed_cache()

    def tearDown(self):
        mock.patch.stopall()
        # Release the pooled SQLite connection(s) maintenance opened before unlinking the temp
        # db, or Windows raises PermissionError (WinError 32: file in use) on the open inode/WAL.
        experience._reset_schema_cache()
        for p in sorted(self.dir.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
        self.dir.rmdir()

    def _seed(self):
        for i in range(3):
            experience.record_subtask("r1", {
                "subtask_id": f"st-{i}", "title": "discord thing", "status": "done",
                "verify_result": {"passed": i > 0}, "session": {"effort": "high", "attempts": 1},
            }, db_path=self.db)

    def test_force_runs_all_steps_and_records_state(self):
        out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertEqual(set(out["steps"]),
                         {"embeddings", "pr_consolidate", "consolidate", "insight",
                          "policy_rebuild", "mine", "evaluate", "prompt_promotion",
                          "lora_distillation", "dpo_distillation", "adapter_promotion",
                          "meta_optimize", "self_play", "evolve", "evolve_promote",
                          "curate", "curriculum_and_report"})
        self.assertTrue(sie._state_path().exists())
        # This run deliberately uses an EMPTY eval suite (EVAL_SUITE_DIR -> nosuite) to stay offline
        # and fast; an empty suite is honestly reported as 'empty_suite', never falsely 'scored'.
        self.assertEqual(out["steps"]["evaluate"]["status"], "empty_suite")

    def test_throttled_second_call_skips(self):
        sie.run_maintenance(force=True, db_path=self.db)
        out = sie.run_maintenance(force=False, db_path=self.db)  # within window
        self.assertEqual(out["skipped"], "not_due")

    def test_kill_switch_skips(self):
        with mock.patch.object(config, "SIE_KILL_SWITCH", True):
            out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertEqual(out["skipped"], "kill_switch")

    def test_lock_prevents_overlap(self):
        lp = sie._lock_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text("999")            # another run holds the lock...
        # ...and it's ALIVE -- so the lock must NOT be reclaimed and maintenance skips. (A lock whose
        # owner PID is dead is correctly reclaimed; that path is covered by test_sie_lock.)
        with mock.patch.object(sie, "_lock_owner_alive", return_value=True):
            out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertEqual(out["skipped"], "locked")

    def test_live_owner_older_than_1h_is_not_stolen(self):
        # B24: a still-LIVE owner must never be reclaimed, no matter how old the lock. The old
        # time-only rule stole any lock >1h, killing long-running (but live) maintenance passes.
        lp = sie._lock_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(str(os.getpid()), encoding="utf-8")   # our pid == provably alive
        old = time.time() - 2 * 3600                          # 2h old
        os.utime(lp, (old, old))
        self.assertIsNone(sie._acquire_lock(), "stole a lock held by a live (but old) owner")

    def test_dead_owner_lock_is_stolen(self):
        # B24 counterpart: a proven-dead owner IS reclaimed immediately (even when fresh).
        lp = sie._lock_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text("999999999", encoding="utf-8")         # implausible -> definitely dead
        got = sie._acquire_lock()
        self.assertIsNotNone(got, "did not reclaim a lock owned by a dead PID")
        self.assertEqual(lp.read_text(encoding="utf-8").strip(), str(os.getpid()))

    def test_maintenance_rebuilds_policy_arms(self):
        self._seed()
        sie.run_maintenance(force=True, db_path=self.db)
        arms = experience.fetch_arms("discord", db_path=self.db)
        self.assertTrue(arms)            # policy rebuilt automatically, no human action

    def test_idempotent_second_force_run(self):
        self._seed()
        sie.run_maintenance(force=True, db_path=self.db)
        sie.run_maintenance(force=True, db_path=self.db)   # must not error or double-count
        arms = {a["action_json"]: a for a in experience.fetch_arms("discord", db_path=self.db)}
        self.assertEqual(arms['{"effort": "high"}']["pulls"], 3)

    def test_evolve_op_registered(self):
        out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertIn("evolve", out["steps"])

    def test_evolve_promote_op_registered(self):
        out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertIn("evolve_promote", out["steps"])

    def test_curate_op_registered(self):
        out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertIn("curate", out["steps"])

    def test_insight_op_registered(self):
        out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertIn("insight", out["steps"])

