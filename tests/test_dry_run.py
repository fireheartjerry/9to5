"""End-to-end dry-run: the FULL pipeline (architect -> plan -> execute -> verify ->
complete) through the real runFull, wired entirely with simulation doubles. This is the
ultimate integration test -- it exercises every phase with no external service."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import platform_core.simulator.simulation as simulation
from platform_core.orchestration import run_loop
from orchestrator import Orchestrator
from state.task import TaskState


class TestDryRun(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "tasks").mkdir()
        (self.dir / "control").mkdir()
        self.work = self.dir / "work"
        self.work.mkdir()
        self._patches = [
            mock.patch.object(config, "STATE_DIR", self.dir / "tasks"),
            mock.patch.object(config, "CONTROL_DIR", self.dir / "control"),
            mock.patch.object(config, "WEB_DASHBOARD", False),
            mock.patch.object(config, "DISCORD_DASHBOARD", False),
            mock.patch("orchestrator.refreshClaudeKnowledge", lambda *a, **k: ""),
            mock.patch("orchestrator.startWebDashboard", lambda *a, **k: None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_full_simulated_run_completes(self):
        st = TaskState.create("build a calculator", 1.0)
        st.setElaboratedGoal("build a calculator")
        st.save()
        orch = simulation.buildOrchestrator(n_subtasks=3)
        summary = orch.runFull(st, work_dir=str(self.work), auto_pr=False, control_mode="watch")
        self.assertEqual(summary["status"], "done")
        self.assertEqual(len(summary["subtasks"]), 3)
        self.assertTrue(all(s["status"] == "done" for s in summary["subtasks"]))
        self.assertTrue(all(s["verified"] for s in summary["subtasks"]))
        self.assertTrue(summary["pr"]["skipped"])
        # work_dir is persisted in meta so resume + every surface remember it (resume-bug guard)
        self.assertEqual(st.meta["work_dir"], str(self.work.resolve()))

    def test_resume_completes_a_stranded_run(self):
        # simulate a crash mid-run: 1 done, 1 stranded in_progress, 1 pending
        st = TaskState.create("build a calculator", 1.0)
        st.setElaboratedGoal("build a calculator")
        st.addSubtask("a", "da")
        st.addSubtask("b", "db")
        st.addSubtask("c", "dc")
        st.updateSubtask("st-001", status="done")
        st.updateSubtask("st-002", status="in_progress")
        st.save()
        summary = simulation.buildOrchestrator().runFull(
            st, work_dir=str(self.work), auto_pr=False, control_mode="watch", resume=True)
        self.assertEqual(summary["status"], "done")
        self.assertEqual([s["status"] for s in st.subtasks], ["done", "done", "done"])

    def test_failing_executor_degrades_to_partial_without_hanging(self):
        # robustness: if the executor can NEVER succeed, the run must finish 'partial'
        # (each subtask retried then failed) -- not hang and not crash.
        st = TaskState.create("build a calculator", 1.0)
        st.setElaboratedGoal("build a calculator")
        st.save()
        def fail(*a, **k): return {"ok": False, "returncode": 1, "stdout": "could not do it",
                                   "is_error": True, "session_id": None}
        orch = Orchestrator(brain=simulation.SimBrain(2), obs=simulation.SimObs(),
                            run_claude=fail, replan=simulation.simReplan, review=simulation.simReview)
        summary = orch.runFull(st, work_dir=str(self.work), auto_pr=False, control_mode="watch")
        self.assertEqual(summary["status"], "partial")
        self.assertTrue(all(s["status"] == "failed" for s in st.subtasks))

    def test_garbage_brain_spec_does_not_crash_the_run(self):
        # robustness: a brain returning junk (non-JSON) for the invocation spec must be
        # sanitized into a usable minimal spec, and the run must still complete.
        class JunkBrain:
            def chat(self, *, model=None, messages=None, **kw):
                import json as _j
                u = next((m.get("content", "") for m in (messages or []) if m.get("role") == "user"), "")
                if "invocation spec" in u.lower():
                    return {"message": {"content": "this is not json at all {{{"}}
                return {"message": {"content": _j.dumps(simulation.SimBrain(2)._plan())}}
        st = TaskState.create("build a calculator", 1.0)
        st.setElaboratedGoal("build a calculator")
        st.save()
        orch = Orchestrator(brain=JunkBrain(), obs=simulation.SimObs(),
                            run_claude=simulation.simRunClaude, replan=simulation.simReplan,
                            review=simulation.simReview)
        summary = orch.runFull(st, work_dir=str(self.work), auto_pr=False, control_mode="watch")
        self.assertEqual(summary["status"], "done")   # sanitizeSpec saved it

    def test_run_is_not_self_referential_in_temp_dir(self):
        # guards the dry-run side-effect fix: a temp work_dir must not trip self-ref detection
        st = TaskState.create("build a calculator", 1.0)
        st.setElaboratedGoal("build a calculator")
        st.save()
        simulation.buildOrchestrator(n_subtasks=1).runFull(
            st, work_dir=str(self.work), auto_pr=False, control_mode="watch")
        self.assertFalse(st.meta.get("is_self_referential"))

    def test_external_goal_about_app_itself_stays_external(self):
        st = TaskState.create("make this app improve itself", 1.0)
        st.setElaboratedGoal("make the target project improve itself")
        st.save()
        simulation.buildOrchestrator(n_subtasks=1).runFull(
            st, work_dir=str(self.work), auto_pr=False, control_mode="watch")
        self.assertFalse(st.meta.get("is_self_referential"))

    def test_external_goal_explicitly_about_9to5_own_code_stays_external(self):
        st = TaskState.create("improve 9to5's own run loop", 1.0)
        st.setElaboratedGoal("improve 9to5's own code")
        st.save()
        self.assertFalse(run_loop._detectSelfReferential(st, str(self.work)))

    def test_project_root_work_dir_is_self_referential(self):
        st = TaskState.create("clean up docs", 1.0)
        st.setElaboratedGoal("clean up docs")
        st.save()
        self.assertTrue(run_loop._detectSelfReferential(st, str(config.PROJECT_ROOT)))


if __name__ == "__main__":
    unittest.main()
