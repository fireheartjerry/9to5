# tests/test_provenance_ledger.py
import os, shutil, stat, tempfile, unittest
from pathlib import Path
from unittest import mock

import config
from memory import experience


def _forceRmtree(path):
    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE); func(p)
        except Exception:
            pass
    shutil.rmtree(path, onerror=_onerror)


class TestLedgerProvenanceColumns(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()); self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_DB_PATH", self.db).start()
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()

    def tearDown(self):
        mock.patch.stopall(); experience._reset_schema_cache(); _forceRmtree(self.dir)

    def test_subtasks_has_adversary_stub_and_provenance(self):
        experience.init(self.db)
        with experience._connect(self.db) as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(subtasks)")}
        self.assertIn("adversary_stub", cols)
        self.assertIn("provenance", cols)

    def test_prompt_variants_and_reflections_and_cache_have_provenance(self):
        experience.init(self.db)
        with experience._connect(self.db) as conn:
            for table in ("prompt_variants", "reflections", "solution_cache"):
                cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                self.assertIn("provenance", cols, f"{table} missing provenance")


if __name__ == "__main__":
    unittest.main()
