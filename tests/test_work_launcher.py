"""Unit tests for the pure /work launcher core (no real subprocess)."""
import os
import subprocess
import unittest
from unittest import mock

import config
from notifications import work_launcher as wl


class TestParseHours(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(wl.parseHours("2"), 2.0)

    def test_suffix_h(self):
        self.assertEqual(wl.parseHours("2h"), 2.0)

    def test_float(self):
        self.assertEqual(wl.parseHours("1.5"), 1.5)

    def test_empty_default(self):
        self.assertEqual(wl.parseHours(""), 1.0)
        self.assertEqual(wl.parseHours(None), 1.0)
        self.assertEqual(wl.parseHours("junk"), 1.0)

    def test_clamp(self):
        self.assertEqual(wl.parseHours("999"), wl.HOURS_MAX)
        self.assertEqual(wl.parseHours("0"), wl.HOURS_MIN)

    def test_nan_inf_rejected(self):
        self.assertEqual(wl.parseHours("inf"), 1.0)
        self.assertEqual(wl.parseHours("nan"), 1.0)


class TestValidate(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(wl.validate(wl.WorkRequest(goal="do x")), [])

    def test_empty_goal(self):
        errs = wl.validate(wl.WorkRequest(goal="   "))
        self.assertTrue(any("goal" in e.lower() for e in errs))

    def test_bad_mode(self):
        errs = wl.validate(wl.WorkRequest(goal="x", mode="turbo"))
        self.assertTrue(any("mode" in e.lower() for e in errs))

    def test_parallel_floor(self):
        errs = wl.validate(wl.WorkRequest(goal="x", parallel=0))
        self.assertTrue(any("parallel" in e.lower() for e in errs))

    def test_bad_workdir(self):
        errs = wl.validate(wl.WorkRequest(goal="x", work_dir="C:/nope/zzz/nonexistent"))
        self.assertTrue(any("work" in e.lower() for e in errs))


class TestBuildArgv(unittest.TestCase):
    def test_core(self):
        argv = wl.buildArgv(wl.WorkRequest(goal="do x", hours=2.0, mode="gated", parallel=2))
        self.assertEqual(argv[0], str(config.VENV_PYTHON))
        self.assertEqual(argv[1], str(config.PROJECT_ROOT / "main.py"))
        self.assertIn("--auto-approve", argv)
        self.assertIn("--goal", argv)
        self.assertIn("do x", argv)
        self.assertIn("gated", argv)

    def test_no_pr_only_when_set(self):
        self.assertNotIn("--no-pr", wl.buildArgv(wl.WorkRequest(goal="x")))
        self.assertIn("--no-pr", wl.buildArgv(wl.WorkRequest(goal="x", no_pr=True)))

    def test_workdir_only_when_set(self):
        self.assertNotIn("--work-dir", wl.buildArgv(wl.WorkRequest(goal="x")))


class TestActiveRun(unittest.TestCase):
    def test_none_when_terminal(self):
        from state.task import TaskState
        st = TaskState.create("g", 1.0)
        st.meta["status"] = "done"
        with mock.patch.object(wl.commands, "resolveTargetTask", return_value=st):
            self.assertIsNone(wl.activeRun())

    def test_returns_when_active(self):
        from state.task import TaskState
        st = TaskState.create("g", 1.0)
        st.meta["status"] = "executing"
        with mock.patch.object(wl.commands, "resolveTargetTask", return_value=st):
            self.assertIs(wl.activeRun(), st)


class TestSpawn(unittest.TestCase):
    def test_spawn_uses_argv(self):
        fake = mock.Mock(pid=4321)
        # opt out of the test-mode spawn guard: this test asserts the real Popen path.
        with mock.patch.object(wl, "_spawnBlocked", return_value=False), \
                mock.patch.object(subprocess, "Popen", return_value=fake) as p, \
                mock.patch("builtins.open", mock.mock_open()):
            pid = wl.spawn(wl.WorkRequest(goal="do x"))
        self.assertEqual(pid, 4321)
        args, kwargs = p.call_args
        self.assertEqual(args[0], wl.buildArgv(wl.WorkRequest(goal="do x")))
        self.assertEqual(kwargs["cwd"], str(config.PROJECT_ROOT))

    def test_spawn_suppressed_in_test_mode(self):
        # the guard must hard-block a real launch and never call Popen during tests
        with mock.patch.object(wl, "_spawnBlocked", return_value=True), \
                mock.patch.object(subprocess, "Popen") as p:
            pid = wl.spawn(wl.WorkRequest(goal="do x"))
        self.assertEqual(pid, wl._SPAWN_BLOCKED_PID)
        p.assert_not_called()

    def test_guard_active_under_unittest_by_default(self):
        # with no env override, simply running under unittest blocks real spawns
        with mock.patch.dict("os.environ", {}, clear=False):
            os.environ.pop("NINE_TO_FIVE_TEST_MODE", None)
            self.assertTrue(wl._spawnBlocked())


class TestResume(unittest.TestCase):
    def test_build_resume_argv(self):
        argv = wl.buildResumeArgv("abc-123")
        self.assertEqual(argv[0], str(config.VENV_PYTHON))
        self.assertEqual(argv[1], str(config.PROJECT_ROOT / "main.py"))
        self.assertIn("--resume", argv)
        self.assertIn("abc-123", argv)

    def test_task_exists(self):
        import tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp())
        (d / "tid.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(config, "STATE_DIR", d):
            self.assertTrue(wl.taskExists("tid"))
            self.assertFalse(wl.taskExists("nope"))

    def test_spawn_resume_uses_argv(self):
        fake = mock.Mock(pid=99)
        # opt out of the test-mode spawn guard: this test asserts the real Popen path.
        with mock.patch.object(wl, "_spawnBlocked", return_value=False), \
                mock.patch.object(subprocess, "Popen", return_value=fake) as p, \
                mock.patch("builtins.open", mock.mock_open()):
            pid = wl.spawnResume("abc-123")
        self.assertEqual(pid, 99)
        self.assertEqual(p.call_args.args[0], wl.buildResumeArgv("abc-123"))


class TestLaunchGlue(unittest.TestCase):
    def test_validate_errors(self):
        self.assertIn("❌", wl.launchOrError(wl.WorkRequest(goal="")))

    def test_blocks_when_active(self):
        from state.task import TaskState
        st = TaskState.create("g", 1.0)
        st.meta["status"] = "executing"
        with mock.patch.object(wl, "activeRun", return_value=st):
            self.assertIn("already active", wl.launchOrError(wl.WorkRequest(goal="x")))

    def test_launch_confirms(self):
        with mock.patch.object(wl, "activeRun", return_value=None), \
                mock.patch.object(wl, "spawn", return_value=123), \
                mock.patch.object(wl, "newestTaskSince", return_value="abcdef12"):
            out = wl.launchOrError(wl.WorkRequest(goal="x"))
        self.assertIn("Launched", out)
        self.assertIn("abcdef12", out)

    def test_resume_no_task(self):
        with mock.patch.object(wl, "taskExists", return_value=False):
            self.assertIn("No such task", wl.resumeOrError("nope"))

    def test_resume_blocks_when_active(self):
        from state.task import TaskState
        st = TaskState.create("g", 1.0)
        st.meta["status"] = "executing"
        with mock.patch.object(wl, "taskExists", return_value=True), \
                mock.patch.object(wl, "activeRun", return_value=st):
            self.assertIn("already active", wl.resumeOrError("abc"))

    def test_resume_spawns(self):
        with mock.patch.object(wl, "taskExists", return_value=True), \
                mock.patch.object(wl, "activeRun", return_value=None), \
                mock.patch.object(wl, "spawnResume", return_value=5):
            self.assertIn("Resuming", wl.resumeOrError("abc"))


if __name__ == "__main__":
    unittest.main()
