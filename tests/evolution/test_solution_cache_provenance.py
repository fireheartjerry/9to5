"""TDD tests for #11b/#23 -- solution_cache.warm_start gated on provenance."""
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


class TestSolutionCacheProvenance(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_DB_PATH", self.db).start()
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()

    def tearDown(self):
        mock.patch.stopall()
        experience._reset_schema_cache()
        _forceRmtree(self.dir)

    def test_unattested_solution_not_warm_started(self):
        """Executor-provenance rows must NOT be served by warm_start (fail-closed)."""
        from learning import solution_cache
        experience.init(self.db)
        with experience._connect(self.db) as conn:
            conn.execute(
                "INSERT INTO solution_cache (signature, spec_json, last_verify_passed, "
                "reuse_count, provenance) VALUES ('sig1', '{}', 1, 0, ?)",
                ('{"origin": "executor"}',))
        self.assertIsNone(solution_cache.warm_start("sig1", db_path=self.db))

    def test_attested_solution_is_warm_started(self):
        """Gold-attested rows (origin=brain, attested_by=sie:gold) MUST be served."""
        from learning import solution_cache
        experience.init(self.db)
        with experience._connect(self.db) as conn:
            conn.execute(
                "INSERT INTO solution_cache (signature, spec_json, last_verify_passed, "
                "reuse_count, provenance) VALUES ('sig2', '{\"prompt\":\"do x\"}', 1, 0, ?)",
                ('{"origin": "brain", "attested_by": "sie:gold"}',))
        self.assertIsNotNone(solution_cache.warm_start("sig2", db_path=self.db))

    def test_missing_provenance_not_warm_started(self):
        """Rows with NULL provenance must NOT be served (fail-closed)."""
        from learning import solution_cache
        experience.init(self.db)
        with experience._connect(self.db) as conn:
            conn.execute(
                "INSERT INTO solution_cache (signature, spec_json, last_verify_passed, "
                "reuse_count, provenance) VALUES ('sig3', '{\"prompt\":\"do y\"}', 1, 0, NULL)")
        self.assertIsNone(solution_cache.warm_start("sig3", db_path=self.db))

    def test_upsert_solution_writes_provenance(self):
        """upsert_solution with provenance= stores it in the row."""
        experience.init(self.db)
        experience.upsert_solution(
            "sig4", '{"prompt":"z"}', verify_passed=True,
            provenance='{"origin":"brain","attested_by":"sie:gold"}',
            db_path=self.db)
        sol = experience.get_solution("sig4", db_path=self.db)
        self.assertIsNotNone(sol)
        self.assertIn("sie:gold", sol.get("provenance", ""))

    def test_upsert_solution_default_provenance_blocks_warm_start(self):
        """upsert_solution with no provenance= defaults to executor -> warm_start returns None."""
        from learning import solution_cache
        experience.init(self.db)
        experience.upsert_solution("sig5", '{"prompt":"w"}', verify_passed=True,
                                   db_path=self.db)
        self.assertIsNone(solution_cache.warm_start("sig5", db_path=self.db))
