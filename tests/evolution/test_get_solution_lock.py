"""experience.get_solution does a reuse-count UPDATE; it must hold _WRITE_LOCK like every other
writer so concurrent calls (parallel subtask workers + the SIE maintenance thread) don't race into
interleaved writes / 'database is locked'."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import config
from memory import experience


class TestGetSolutionLock(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        self._p = mock.patch.object(config, "EXPERIENCE_DB_PATH", self.db)
        self._p.start()
        experience.init(self.db)

    def tearDown(self):
        self._p.stop()
        experience._reset_schema_cache()

    def test_concurrent_get_solution_no_error_and_counts(self):
        sig = "sig-1"
        experience.upsert_solution(sig, '{"prompt": "x"}', verify_passed=True,
                                   provenance='{"origin":"test"}', db_path=self.db)
        errors = []

        def worker():
            try:
                for _ in range(20):
                    experience.get_solution(sig, db_path=self.db)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, [], f"concurrent get_solution raised: {errors[:2]}")
        row = experience.get_solution(sig, db_path=self.db)
        self.assertIsNotNone(row)
        self.assertGreaterEqual(row["reuse_count"], 120)   # 6*20 increments all landed
