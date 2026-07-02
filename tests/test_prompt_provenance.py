"""TDD: champion body is gated on provenance (fix #2 -- Task 4.4).

An unattested (executor-origin) champion body must be refused; only a
gate-attested body may be served.  The in-code fallback is returned
whenever the gate rejects.
"""
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from memory import experience


def _forceRmtree(path):
    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    shutil.rmtree(path, onerror=_onerror)


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
        from learning import prompts
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
        from learning import prompts
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
        from learning import prompts
        experience.init(self.db)
        prompts.champion_id("planner", "PLANNER DEFAULT", db_path=self.db)
        got = prompts.get("planner", "FALLBACK", db_path=self.db)
        self.assertEqual(got, "PLANNER DEFAULT")
