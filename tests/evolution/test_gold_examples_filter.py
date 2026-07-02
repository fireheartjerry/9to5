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


class TestGoldFilter(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()); self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_DB_PATH", self.db).start()
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()

    def tearDown(self):
        mock.patch.stopall(); experience._reset_schema_cache(); _forceRmtree(self.dir)

    def _insert(self, st_id, *, verdict, stub):
        with experience._connect(self.db) as conn:
            conn.execute(
                "INSERT INTO subtasks (run_id, st_id, position, verify_passed, attempt_count, "
                "adversary_verdict, adversary_stub) VALUES (?,?,?,?,?,?,?)",
                ("r1", st_id, 0, 1, 1, verdict, stub))

    def test_stub_approved_is_not_gold(self):
        experience.init(self.db)
        self._insert("real", verdict="approved", stub=0)
        self._insert("stubbed", verdict="approved", stub=1)
        self._insert("never", verdict=None, stub=None)
        gold = {r["st_id"] for r in experience.gold_examples(self.db)}
        self.assertIn("real", gold)
        self.assertNotIn("stubbed", gold)   # stub approval is not evidence
        self.assertNotIn("never", gold)     # never-reviewed is not evidence
