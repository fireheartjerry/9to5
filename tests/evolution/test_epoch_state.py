import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import platform_core.core.epoch as epoch
from state.task import TaskState


class TestEpochInMeta(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        mock.patch.object(config, "STATE_DIR", self.dir).start()

    def tearDown(self):
        mock.patch.stopall()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_meta_has_epoch_field_default_none(self):
        st = TaskState.create("g", 1.0)
        self.assertIn("epoch", st.meta)
        self.assertIsNone(st.meta["epoch"])

    def test_set_epoch_persists(self):
        st = TaskState.create("g", 1.0)
        snap = epoch.snapshot(universe={"hard_boundaries": [".env"]})
        st.setEpoch(snap)
        self.assertEqual(TaskState.load(st.task_id).meta["epoch"]["universe"]["hard_boundaries"],
                         [".env"])
