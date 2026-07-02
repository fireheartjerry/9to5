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


class TestStubCarry(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()); self.db = self.dir / "experience.db"
        self.state_dir = self.dir / "state"; self.state_dir.mkdir()
        mock.patch.object(config, "EXPERIENCE_DB_PATH", self.db).start()
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()
        mock.patch.object(config, "STATE_DIR", self.state_dir).start()

    def tearDown(self):
        mock.patch.stopall(); experience._reset_schema_cache(); _forceRmtree(self.dir)

    def test_stub_review_persists_adversary_stub_1(self):
        from state.task import TaskState
        st = TaskState.create("g", 1.0)
        # addSubtask signature: (title, description, ...)
        sub = st.addSubtask("title", "desc")
        st.addAdversaryReview(sub["subtask_id"], "heartbeat", "approved", stub=True)
        with experience._connect(self.db) as conn:
            row = conn.execute("SELECT adversary_stub FROM subtasks WHERE st_id=?",
                               (sub["subtask_id"],)).fetchone()
        self.assertIsNotNone(row, "ledger row was not written")
        self.assertEqual(row["adversary_stub"], 1)

    def test_real_review_persists_adversary_stub_0(self):
        from state.task import TaskState
        st = TaskState.create("g", 1.0)
        sub = st.addSubtask("title", "desc")
        st.addAdversaryReview(sub["subtask_id"], "heartbeat", "approved", stub=False)
        with experience._connect(self.db) as conn:
            row = conn.execute("SELECT adversary_stub FROM subtasks WHERE st_id=?",
                               (sub["subtask_id"],)).fetchone()
        self.assertIsNotNone(row, "ledger row was not written")
        self.assertIn(row["adversary_stub"], (0, None))  # not a stub
