"""Tests for working-directory selection: persistence in task meta, resume remembering
it, surfacing in status/run embeds, and launcher validation."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from notifications import branding
from notifications import work_launcher as wl
from state.task import TaskState


class TestWorkDirState(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._patch = mock.patch.object(config, "STATE_DIR", self.dir)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_create_has_work_dir_field(self):
        st = TaskState.create("g", 1.0)
        self.assertIn("work_dir", st.meta)
        self.assertIsNone(st.meta["work_dir"])

    def test_set_work_dir_resolves_absolute_and_persists(self):
        st = TaskState.create("g", 1.0)
        st.setWorkDir(str(self.dir))
        self.assertEqual(st.meta["work_dir"], str(self.dir.resolve()))
        # persisted across a reload
        self.assertEqual(TaskState.load(st.task_id).meta["work_dir"], str(self.dir.resolve()))


class TestWorkDirSurfaces(unittest.TestCase):
    def _state(self):
        st = TaskState.create("build a thing", 1.0)
        st.meta["work_dir"] = "/home/user/myproject"
        st.addSubtask("a", "d")
        return st

    def test_status_embed_shows_work_dir(self):
        e = branding.statusEmbed(self._state(), bus=None)
        blob = " ".join(f["value"] for f in e["fields"])
        self.assertIn("/home/user/myproject", blob)

    def test_run_embed_shows_work_dir(self):
        e = branding.runEmbed(self._state())
        blob = " ".join(f["value"] for f in e["fields"])
        self.assertIn("/home/user/myproject", blob)


class TestWorkDirLauncherValidation(unittest.TestCase):
    def test_missing_work_dir_is_rejected(self):
        errs = wl.validate(wl.WorkRequest(goal="x", work_dir="/no/such/dir/xyz"))
        self.assertTrue(any("work_dir" in e for e in errs))

    def test_existing_work_dir_ok(self):
        with tempfile.TemporaryDirectory() as d:
            errs = wl.validate(wl.WorkRequest(goal="x", work_dir=d))
            self.assertEqual(errs, [])

    def test_argv_passes_resolved_work_dir(self):
        with tempfile.TemporaryDirectory() as d:
            argv = wl.buildArgv(wl.WorkRequest(goal="x", work_dir=d))
            self.assertIn("--work-dir", argv)
            self.assertIn(str(Path(d).resolve()), argv)


if __name__ == "__main__":
    unittest.main()
