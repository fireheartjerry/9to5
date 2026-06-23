"""Unit tests for the SIE Layer 3 prompt registry (learning/prompts.py)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import prompts
from memory import experience


class TestPromptRegistry(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"

    def tearDown(self):
        mock.patch.stopall()
        # release pooled SQLite connection(s) before unlinking the temp db (Windows WinError 32)
        experience._reset_schema_cache()
        for p in self.dir.rglob("*"):
            if p.is_file():
                p.unlink()
        self.dir.rmdir()

    def test_get_is_byte_identical_until_promotion(self):
        default = "ORIGINAL CONSTITUTION"
        # First call seeds + returns the exact default; second returns the seeded champion.
        self.assertEqual(prompts.get("orchestrator", default, db_path=self.db), default)
        self.assertEqual(prompts.get("orchestrator", default, db_path=self.db), default)
        champs = experience.fetch_variants("orchestrator", "champion", db_path=self.db)
        self.assertEqual(len(champs), 1)
        self.assertEqual(champs[0]["body"], default)

    def test_propose_and_promote_overrides_default(self):
        default = "v1 body"
        prompts.get("orchestrator", default, db_path=self.db)            # seed champion
        cid = prompts.propose("orchestrator", "v2 better body", db_path=self.db)
        # Still the champion until promotion:
        self.assertEqual(prompts.get("orchestrator", default, db_path=self.db), default)
        self.assertTrue(prompts.promote("orchestrator", cid, db_path=self.db))
        self.assertEqual(prompts.get("orchestrator", default, db_path=self.db), "v2 better body")
        # Exactly one champion at all times:
        self.assertEqual(len(experience.fetch_variants("orchestrator", "champion", db_path=self.db)), 1)

    def test_dedup_same_body(self):
        prompts.get("orchestrator", "same", db_path=self.db)
        a = experience.register_variant("orchestrator", "same", db_path=self.db)
        b = experience.register_variant("orchestrator", "same", db_path=self.db)
        self.assertEqual(a, b)   # identical body -> same id, no duplicate row

    def test_champion_id_seeds_when_missing(self):
        cid = prompts.champion_id("planner", "planner default", db_path=self.db)
        self.assertIsNotNone(cid)


if __name__ == "__main__":
    unittest.main()
