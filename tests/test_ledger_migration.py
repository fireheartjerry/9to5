"""The idempotent ADD COLUMN migration helper for the Experience Ledger."""
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


class TestLedgerMigration(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_DB_PATH", self.db).start()
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()

    def tearDown(self):
        mock.patch.stopall()
        experience._reset_schema_cache()
        _forceRmtree(self.dir)

    def test_ensure_columns_adds_missing_column_idempotently(self):
        experience.init(self.db)
        with experience._connect(self.db) as conn:
            experience._ensureColumns(conn, "subtasks", {"spike_col": "INTEGER"})
            experience._ensureColumns(conn, "subtasks", {"spike_col": "INTEGER"})  # again
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(subtasks)")}
        self.assertIn("spike_col", cols)


if __name__ == "__main__":
    unittest.main()
