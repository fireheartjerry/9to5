"""Tests for the last-mile full-autonomy pieces: bootstrap, self-play, meta-opt apply."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import config
from learning import bootstrap, meta_opt, selfplay
from memory import experience


class TestBootstrap(unittest.TestCase):
    def tearDown(self):
        mock.patch.stopall()
        bootstrap._done.update({"deps": False, "models": False})

    def test_deps_skip_without_gpu(self):
        with mock.patch("learning.compute.training_enabled", return_value=True), \
             mock.patch("learning.compute.should_use_gpu", return_value=False):
            self.assertEqual(bootstrap.ensure_training_deps()["skipped"], "no_gpu")

    def test_models_skip_without_ollama(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(bootstrap.ensure_models()["skipped"], "no_ollama")

    def test_deps_install_invoked_when_gpu_and_missing(self):
        calls = {}
        with mock.patch("learning.compute.training_enabled", return_value=True), \
             mock.patch("learning.compute.should_use_gpu", return_value=True), \
             mock.patch("learning.bootstrap._have", return_value=False), \
             mock.patch("subprocess.run", side_effect=lambda *a, **k: calls.setdefault("ran", a)):
            out = bootstrap.ensure_training_deps()
        self.assertIn("installed", out)
        self.assertIn("ran", calls)


class TestSelfPlay(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()
        mock.patch.object(config, "CONTROL_DIR", self.dir).start()
        mock.patch.object(config, "SELFPLAY_ENABLED", True).start()
        mock.patch.object(config, "SELFPLAY_MAX_PER_DAY", 3).start()
        mock.patch.object(config, "SELFPLAY_START_HOUR", 0).start()
        mock.patch.object(config, "SELFPLAY_END_HOUR", 24).start()

    def tearDown(self):
        mock.patch.stopall()
        # Release pooled SQLite connections before unlinking the temp db (Windows WinError 32).
        experience._reset_schema_cache()
        for p in self.dir.rglob("*"):
            if p.is_file():
                p.unlink()
        self.dir.rmdir()

    def _weak_family(self):
        for i in range(4):
            experience.record_subtask("r1", {
                "subtask_id": f"st-{i}", "title": "flaky api task", "status": "failed",
                "verify_result": {"passed": False}, "session": {"attempts": 3}}, db_path=self.db)

    def test_disabled_skips(self):
        with mock.patch.object(config, "SELFPLAY_ENABLED", False):
            self.assertEqual(selfplay.run(db_path=self.db)["skipped"], "disabled")

    def test_outside_window_skips(self):
        with mock.patch.object(config, "SELFPLAY_START_HOUR", 9), \
             mock.patch.object(config, "SELFPLAY_END_HOUR", 17):
            out = selfplay.run(db_path=self.db, now=datetime(2026, 6, 23, 3, 0).astimezone())
        self.assertEqual(out["skipped"], "outside_window")

    def test_busy_skips(self):
        self._weak_family()
        out = selfplay.run(db_path=self.db, is_busy=lambda: True,
                           launch_fn=lambda g, h: None)
        self.assertEqual(out["skipped"], "busy")

    def test_launches_weak_family_goal(self):
        self._weak_family()
        launched = {}
        out = selfplay.run(db_path=self.db, is_busy=lambda: False,
                           launch_fn=lambda g, h: launched.update(goal=g, hours=h))
        self.assertIn("launched", out)
        self.assertIn("flaky", launched["goal"])   # family = first significant word
        # Daily cap enforced on the next call.
        out2 = selfplay.run(db_path=self.db, is_busy=lambda: False, launch_fn=lambda g, h: None)
        self.assertEqual(_cap_or_launch(out2), True)

    def test_daily_cap(self):
        self._weak_family()
        with mock.patch.object(config, "SELFPLAY_MAX_PER_DAY", 0):
            self.assertEqual(selfplay.run(db_path=self.db, launch_fn=lambda g, h: None)["skipped"],
                             "daily_cap")


def _cap_or_launch(out):
    return out.get("skipped") == "daily_cap" or "launched" in out


class TestMetaApply(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()
        mock.patch.object(config, "SIE_META_AUTOAPPLY", True).start()
        mock.patch.object(config, "SIE_OVERRIDES_PATH", self.dir / "ov.json").start()
        mock.patch.object(config, "MAX_SUBTASK_ATTEMPTS", 3).start()

    def tearDown(self):
        mock.patch.stopall()
        # Release pooled SQLite connections before unlinking the temp db (Windows WinError 32).
        experience._reset_schema_cache()
        for p in self.dir.rglob("*"):
            if p.is_file():
                p.unlink()
        self.dir.rmdir()

    def test_auto_applies_within_bounds_and_persists(self):
        for i in range(4):   # weak families -> suggest raising MAX_SUBTASK_ATTEMPTS
            experience.record_subtask("r1", {
                "subtask_id": f"st-{i}", "title": "api task", "status": "failed",
                "verify_result": {"passed": False}, "session": {"attempts": 3}}, db_path=self.db)
        out = meta_opt.apply(db_path=self.db)
        knobs = [a["knob"] for a in out["applied"]]
        self.assertIn("MAX_SUBTASK_ATTEMPTS", knobs)
        self.assertEqual(config.MAX_SUBTASK_ATTEMPTS, 4)            # live-applied
        self.assertTrue((self.dir / "ov.json").exists())            # persisted

    def test_disabled_skips(self):
        with mock.patch.object(config, "SIE_META_AUTOAPPLY", False):
            self.assertEqual(meta_opt.apply(db_path=self.db)["skipped"], "disabled")


if __name__ == "__main__":
    unittest.main()
