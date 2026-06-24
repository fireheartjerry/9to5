import tempfile, unittest
from pathlib import Path
from unittest import mock

import config
from state.task import TaskState


class TestCoherence(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        mock.patch.object(config, "STATE_DIR", self.dir).start()

    def tearDown(self):
        mock.patch.stopall()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_save_increments_state_epoch(self):
        st = TaskState.create("g", 1.0)
        first = st.meta.get("state_epoch")
        self.assertEqual(first, 0)
        st.meta["status"] = "running"
        st.save()
        self.assertGreater(st.meta["state_epoch"], first)

    def test_no_importlib_reload_in_resilience_source(self):
        src = (Path(config.PROJECT_ROOT) / "resilience.py").read_text(encoding="utf-8")
        # In-process restart must keep the pinned bytecode; self-edits adopt only on a
        # fresh process. A reload would re-enter edited code incoherently.
        self.assertNotIn("importlib.reload", src)


if __name__ == "__main__":
    unittest.main()
