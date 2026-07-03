"""Unit tests for the SIE Layer 3 prompt registry (learning/prompts.py).

Consolidated from test_prompts.py and test_prompt_provenance.py: both test
learning/prompts.py -- the first covers the champion/challenger registry
(get/propose/promote/dedup), the second covers the provenance gate that refuses
an unattested (executor-origin) champion body (fix #2 -- Task 4.4).
"""
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import prompts
from memory import experience


def _forceRmtree(path):
    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    shutil.rmtree(path, onerror=_onerror)


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


# ---------------------------------------------------------------------------
# TDD: champion body is gated on provenance (fix #2 -- Task 4.4).
#
# An unattested (executor-origin) champion body must be refused; only a
# gate-attested body may be served.  The in-code fallback is returned
# whenever the gate rejects.
# ---------------------------------------------------------------------------

class TestPromptProvenance(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_DB_PATH", self.db).start()
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()

    def tearDown(self):
        mock.patch.stopall()
        experience._reset_schema_cache()
        _forceRmtree(self.dir)

    def test_unattested_champion_body_is_rejected(self):
        """A champion row whose provenance is executor-origin must be refused."""
        experience.init(self.db)
        with experience._connect(self.db) as conn:
            conn.execute(
                "INSERT INTO prompt_variants "
                "(role, version, body_hash, body, state, provenance) "
                "VALUES ('orchestrator', 1, 'h1', 'MALICIOUS CONSTITUTION', 'champion', ?)",
                ('{"origin": "executor"}',))
        fallback = "BUILTIN CONSTITUTION"
        got = prompts.get("orchestrator", fallback, db_path=self.db)
        self.assertEqual(got, fallback)   # unattested body refused -> in-code constant

    def test_attested_champion_body_is_served(self):
        """A champion row attested by the promotion gate must be served."""
        experience.init(self.db)
        with experience._connect(self.db) as conn:
            conn.execute(
                "INSERT INTO prompt_variants "
                "(role, version, body_hash, body, state, provenance) "
                "VALUES ('orchestrator', 1, 'h2', 'TRUSTED CONSTITUTION', 'champion', ?)",
                ('{"origin": "brain", "attested_by": "sie:promotion-gate"}',))
        got = prompts.get("orchestrator", "BUILTIN", db_path=self.db)
        self.assertEqual(got, "TRUSTED CONSTITUTION")  # gate-attested body survives

    def test_champion_id_seed_is_servable_by_get(self):
        # A champion seeded via champion_id() must carry trusted provenance, so a later
        # get() serves it (the in-code default) instead of quarantining it.
        experience.init(self.db)
        prompts.champion_id("planner", "PLANNER DEFAULT", db_path=self.db)
        got = prompts.get("planner", "FALLBACK", db_path=self.db)
        self.assertEqual(got, "PLANNER DEFAULT")
