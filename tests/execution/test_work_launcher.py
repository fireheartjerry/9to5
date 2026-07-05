"""Unit tests for the pure /work launcher core (no real subprocess).

Also covers: working-directory selection (persistence in task meta, resume remembering
it, surfacing in status/run embeds, and launcher validation), and liveness -- a LIVE
orchestrator run must never be classed 'stale' (which mis-aborts it and lets a second
run double-spawn on the same repo). Liveness is heartbeat.isRunAlive -- heartbeat fresh
OR recorded pid alive; the old mtime heuristic is gone. Stale cleanup goes through the
bus + task_io.reapDeadRun, never a direct task-JSON write from the bot process."""

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import config
from notifications import branding
from notifications import work_launcher as wl
from platform_core.core import fsio
from state.task import TaskState

DEAD_PID = 999999999  # implausible -> definitely dead


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

    def test_bad_work_profile(self):
        errs = wl.validate(wl.WorkRequest(goal="x", work_profile="nope=99"))
        self.assertTrue(any("axis" in e.lower() for e in errs))


class TestBuildArgv(unittest.TestCase):
    def test_core(self):
        argv = wl.buildArgv(wl.WorkRequest(goal="do x", hours=2.0, mode="gated", parallel=2))
        self.assertEqual(argv[0], wl._pythonExe())  # venv python when present, else sys.executable
        self.assertEqual(argv[1], str(config.PROJECT_ROOT / "main.py"))
        self.assertIn("--auto-approve", argv)
        self.assertIn("--goal", argv)
        self.assertIn("do x", argv)
        self.assertIn("gated", argv)

    def test_no_pr_only_when_set(self):
        self.assertNotIn("--no-pr", wl.buildArgv(wl.WorkRequest(goal="x")))
        self.assertIn("--no-pr", wl.buildArgv(wl.WorkRequest(goal="x", no_pr=True)))

    def test_interpreter_falls_back_to_sys_executable_when_venv_missing(self):
        """REGRESSION: in a git worktree / checkout with no ``venv/`` the venv python
        (``config.VENV_PYTHON`` = ``<root>/venv/Scripts/python.exe``) does not exist, and
        ``subprocess.Popen(argv)`` raised WinError 2. buildArgv must fall back to the running
        interpreter (``sys.executable``), which is always present and dep-complete."""
        import sys

        missing = Path(config.PROJECT_ROOT) / "no-such-venv" / "python.exe"
        self.assertFalse(missing.exists())
        with mock.patch.object(config, "VENV_PYTHON", missing):
            argv = wl.buildArgv(wl.WorkRequest(goal="x"))
            self.assertEqual(argv[0], sys.executable)
            resume = wl.buildResumeArgv("11111111-1111-1111-1111-111111111111")
            self.assertEqual(resume[0], sys.executable)

    def test_night_mode_forces_pr_feedback(self):
        argv = wl.buildArgv(wl.WorkRequest(goal="x", no_pr=True, night_mode=True))
        self.assertNotIn("--no-pr", argv)

    def test_workdir_only_when_set(self):
        self.assertNotIn("--work-dir", wl.buildArgv(wl.WorkRequest(goal="x")))

    def test_work_profile_passed_to_cli(self):
        argv = wl.buildArgv(wl.WorkRequest(goal="x", work_profile="auditor"))
        self.assertIn("--work-profile", argv)
        self.assertIn("auditor", argv)

    def test_launch_id_passed_to_cli(self):
        self.assertNotIn("--launch-id", wl.buildArgv(wl.WorkRequest(goal="x")))
        argv = wl.buildArgv(wl.WorkRequest(goal="x", launch_id="abc123"))
        self.assertIn("--launch-id", argv)
        self.assertIn("abc123", argv)


class TestActiveRun(unittest.TestCase):
    def test_none_when_terminal(self):
        st = TaskState.create("g", 1.0)
        st.meta["status"] = "done"
        with mock.patch.object(wl.commands, "resolveTargetTask", return_value=st):
            self.assertIsNone(wl.activeRun())

    def test_returns_when_active(self):
        st = TaskState.create("g", 1.0)
        st.meta["status"] = "executing"
        st.meta["run_pid"] = os.getpid()  # liveness: this process vouches for the run
        st.save()
        with mock.patch.object(wl.commands, "resolveTargetTask", return_value=st):
            self.assertIs(wl.activeRun(), st)


class TestSpawn(unittest.TestCase):
    def test_spawn_uses_argv(self):
        fake = mock.Mock(pid=4321)
        # opt out of the test-mode spawn guard: this test asserts the real Popen path.
        with (
            mock.patch.object(wl, "_spawnBlocked", return_value=False),
            mock.patch.object(subprocess, "Popen", return_value=fake) as p,
            mock.patch("builtins.open", mock.mock_open()),
        ):
            pid = wl.spawn(wl.WorkRequest(goal="do x"))
        self.assertEqual(pid, 4321)
        args, kwargs = p.call_args
        self.assertEqual(args[0], wl.buildArgv(wl.WorkRequest(goal="do x")))
        self.assertEqual(kwargs["cwd"], str(config.PROJECT_ROOT))

    def test_spawn_suppressed_in_test_mode(self):
        # the guard must hard-block a real launch and never call Popen during tests
        with (
            mock.patch.object(wl, "_spawnBlocked", return_value=True),
            mock.patch.object(subprocess, "Popen") as p,
        ):
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
        self.assertEqual(argv[0], wl._pythonExe())  # venv python when present, else sys.executable
        self.assertEqual(argv[1], str(config.PROJECT_ROOT / "main.py"))
        self.assertIn("--resume", argv)
        self.assertIn("abc-123", argv)

    def test_task_exists(self):
        tid = "11111111-1111-4111-8111-111111111111"
        missing_id = "22222222-2222-4222-8222-222222222222"
        d = Path(tempfile.mkdtemp())
        (d / f"{tid}.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(config, "STATE_DIR", d):
            self.assertTrue(wl.taskExists(tid))
            self.assertFalse(wl.taskExists(missing_id))

    def test_task_exists_rejects_path_traversal(self):
        # BUG (fresh bug hunt): a non-UUID task_id must never confirm a file's existence
        # outside STATE_DIR -- taskExists is reachable from the unauthenticated /run command.
        d = Path(tempfile.mkdtemp())
        (d / "sibling.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(config, "STATE_DIR", d / "tasks"):
            self.assertFalse(wl.taskExists("../sibling"))

    def test_spawn_resume_uses_argv(self):
        fake = mock.Mock(pid=99)
        # opt out of the test-mode spawn guard: this test asserts the real Popen path.
        with (
            mock.patch.object(wl, "_spawnBlocked", return_value=False),
            mock.patch.object(subprocess, "Popen", return_value=fake) as p,
            mock.patch("builtins.open", mock.mock_open()),
        ):
            pid = wl.spawnResume("abc-123")
        self.assertEqual(pid, 99)
        self.assertEqual(p.call_args.args[0], wl.buildResumeArgv("abc-123"))


class TestLaunchGlue(unittest.TestCase):
    def test_validate_errors(self):
        self.assertIn("❌", wl.launchOrError(wl.WorkRequest(goal="")))

    def test_blocks_when_active(self):
        st = TaskState.create("g", 1.0)
        st.meta["status"] = "executing"
        with mock.patch.object(wl, "activeRun", return_value=st):
            self.assertIn("already active", wl.launchOrError(wl.WorkRequest(goal="x")))

    def test_launch_confirms_via_handshake(self):
        with (
            mock.patch.object(wl, "activeRun", return_value=None),
            mock.patch.object(wl, "spawn", return_value=123),
            mock.patch.object(wl, "waitForLaunch", return_value="abcdef12") as wfl,
        ):
            out = wl.launchOrError(wl.WorkRequest(goal="x"))
        self.assertIn("Launched", out)
        self.assertIn("abcdef12", out)
        # the handshake token generated for the spawn is the one polled for
        self.assertTrue(wfl.call_args.args[0])

    def test_launch_summary_includes_profile(self):
        with (
            mock.patch.object(wl, "activeRun", return_value=None),
            mock.patch.object(wl, "spawn", return_value=123),
            mock.patch.object(wl, "waitForLaunch", return_value="abcdef12"),
        ):
            out = wl.launchOrError(wl.WorkRequest(goal="x", work_profile="auditor"))
        self.assertIn("Profile:", out)
        self.assertIn("auditor", out)

    def test_handshake_reads_launch_file(self):
        import json

        config.LAUNCH_DIR.mkdir(parents=True, exist_ok=True)
        (config.LAUNCH_DIR / "tok1.json").write_text(json.dumps({"task_id": "t-42"}), encoding="utf-8")
        self.assertEqual(wl.waitForLaunch("tok1", timeout_s=0.2, poll_s=0.01), "t-42")
        self.assertIsNone(wl.waitForLaunch("missing", timeout_s=0.05, poll_s=0.01))

    def test_double_launch_spawns_exactly_once(self):
        import threading

        spawned = []

        def slow_spawn(req):
            spawned.append(req)
            import time as _t

            _t.sleep(0.2)  # hold the launch window open so the second call collides
            return 123

        results = []
        with (
            mock.patch.object(wl, "activeRun", return_value=None),
            mock.patch.object(wl, "spawn", side_effect=slow_spawn),
            mock.patch.object(wl, "waitForLaunch", return_value="abcdef12"),
        ):
            ts = [
                threading.Thread(target=lambda: results.append(wl.launchOrError(wl.WorkRequest(goal="x"))))
                for _ in range(2)
            ]
            for t in ts:
                t.start()
            for t in ts:
                t.join(timeout=10)
        self.assertEqual(len(spawned), 1, "concurrent launchOrError double-spawned")
        self.assertEqual(sorted("Launched" in r for r in results), [False, True])
        self.assertTrue(any("already in progress" in r for r in results))

    def test_resume_no_task(self):
        with mock.patch.object(wl, "taskExists", return_value=False):
            self.assertIn("No such task", wl.resumeOrError("nope"))

    def test_resume_blocks_when_active(self):
        st = TaskState.create("g", 1.0)
        st.meta["status"] = "executing"
        with (
            mock.patch.object(wl, "taskExists", return_value=True),
            mock.patch.object(wl, "activeRun", return_value=st),
        ):
            self.assertIn("already active", wl.resumeOrError("abc"))

    def test_resume_spawns(self):
        with (
            mock.patch.object(wl, "taskExists", return_value=True),
            mock.patch.object(wl, "activeRun", return_value=None),
            mock.patch.object(wl, "spawnResume", return_value=5),
        ):
            self.assertIn("Resuming", wl.resumeOrError("abc"))


# ---------------------------------------------------------------------------
# Working-directory selection: persistence in task meta, resume remembering it,
# surfacing in status/run embeds, and launcher validation.
# ---------------------------------------------------------------------------


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

    def test_external_readiness_warns_for_non_git_dir(self):
        with tempfile.TemporaryDirectory() as d:
            warnings = wl.externalReadiness(wl.WorkRequest(goal="x", work_dir=d))
            self.assertTrue(any("not a git repo" in w for w in warnings))

    def test_external_readiness_warns_for_git_repo_without_origin(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", d], check=True, capture_output=True, text=True)
            warnings = wl.externalReadiness(wl.WorkRequest(goal="x", work_dir=d))
            self.assertTrue(any("no `origin` remote" in w for w in warnings))

    def test_launch_reply_includes_external_readiness_warnings(self):
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(wl, "activeRun", return_value=None),
            mock.patch.object(wl, "spawn", return_value=123),
            mock.patch.object(wl, "waitForLaunch", return_value="abcdef12"),
        ):
            out = wl.launchOrError(wl.WorkRequest(goal="x", work_dir=d))
        self.assertIn("Launched run", out)
        self.assertIn("not a git repo", out)


# ---------------------------------------------------------------------------
# Liveness: a LIVE orchestrator run must never be classed 'stale'.
# ---------------------------------------------------------------------------


def _task(status="executing"):
    st = TaskState.create("goal", 1.0)
    st.meta["status"] = status
    st.save()
    return st


def _age(st, seconds=100000):
    old = time.time() - seconds
    os.utime(st.path(), (old, old))


class TestStaleLiveness(unittest.TestCase):
    def test_live_pid_not_stale_even_with_ancient_mtime(self):
        st = _task()
        st.meta["run_pid"] = os.getpid()  # this process is alive
        st.save()
        _age(st)  # file untouched for ~27h
        self.assertFalse(wl._isStale(st), "a live run was misread as stale")

    def test_created_status_live_pid_not_stale(self):
        # A still-initializing run (status 'created') stamps run_pid BEFORE the slow Ollama
        # elaboration, so even a multi-minute elaboration is NOT mis-declared stale.
        st = _task(status="created")
        st.meta["run_pid"] = os.getpid()
        st.save()
        _age(st, seconds=1000)
        self.assertFalse(
            wl._isStale(st), "a live still-elaborating run was misread as stale (double-spawn risk)"
        )

    def test_fresh_heartbeat_not_stale_despite_dead_pid_and_old_mtime(self):
        # The heartbeat is authoritative when fresh: an old task-file mtime means nothing.
        st = _task()
        st.meta["run_pid"] = DEAD_PID
        st.save()
        _age(st)
        fsio.atomicWriteJson(
            config.HEARTBEAT_DIR / f"{st.task_id}.json", {"pid": DEAD_PID, "seq": 3, "ts": time.time()}
        )
        self.assertFalse(wl._isStale(st), "a heartbeat-fresh run was misread as stale")

    def test_dead_pid_is_stale(self):
        st = _task()
        st.meta["run_pid"] = DEAD_PID
        st.save()
        self.assertTrue(wl._isStale(st))

    def test_no_pid_no_heartbeat_is_stale(self):
        st = _task()
        st.meta.pop("run_pid", None)
        st.save()
        self.assertTrue(wl._isStale(st), "a task with no liveness evidence at all should be stale")


class TestStaleReap(unittest.TestCase):
    """activeRun's stale path: bus abort + reapDeadRun -- NEVER a direct task-JSON write."""

    def test_stale_run_reaped_via_bus_and_escape_hatch(self):
        st = _task()
        st.meta["run_pid"] = DEAD_PID
        st.save()
        with (
            mock.patch.object(wl.commands, "resolveTargetTask", return_value=st),
            mock.patch.object(
                TaskState, "setStatus", side_effect=AssertionError("bot wrote task JSON directly")
            ),
        ):
            self.assertIsNone(wl.activeRun())
        from platform_core.runtime.control import ControlBus

        bus = ControlBus(st.task_id)
        self.assertTrue(bus.isAbort(), "stale cleanup did not request abort on the bus")
        ops = bus.drainOps()
        self.assertTrue(any(o.get("op") == "mark_stale" for o in ops), f"no breadcrumb op: {ops}")
        self.assertEqual(
            TaskState.load(st.task_id).meta["status"],
            "aborted",
            "dead run was not finalized through reapDeadRun",
        )

    def test_live_run_never_reaped(self):
        st = _task()
        st.meta["run_pid"] = os.getpid()
        st.save()
        with mock.patch.object(wl.commands, "resolveTargetTask", return_value=st):
            self.assertIs(wl.activeRun(), st)
        self.assertEqual(TaskState.load(st.task_id).meta["status"], "executing")
