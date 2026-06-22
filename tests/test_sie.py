"""Unit tests for the Self-Improvement Orchestrator auto-runner (learning/sie.py)."""
import tempfile
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
        # Keep maintenance fully offline + fast: no embedder.
        mock.patch.object(retrieval, "_embed_call", return_value=None).start()
        retrieval.reset_embed_cache()

    def tearDown(self):
        mock.patch.stopall()
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
                         {"embeddings", "consolidate", "policy_rebuild", "evaluate",
                          "prompt_promotion", "lora_distillation", "dpo_distillation"})
        self.assertTrue(sie._state_path().exists())
        self.assertEqual(out["steps"]["evaluate"]["status"], "no_runner")

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
        lp.write_text("999")            # simulate another run holding the lock
        out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertEqual(out["skipped"], "locked")

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


if __name__ == "__main__":
    unittest.main()
