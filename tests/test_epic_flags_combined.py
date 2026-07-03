"""Combined epic-flags integration smoke test.

No single-flag test exercises more than one epic at a time -- each is tested ON vs OFF in
isolation (tests/test_*_config.py). This test turns SEVERAL epic flags on TOGETHER against a
real (BuilderBrain) run and proves the run still reaches a graceful terminal status with real
forward progress -- the direct regression guard for the Epic-5 Society wiring bugs (A/B/C) fixed
alongside this test: a run that silently fails every subtask via crash-containment would still
reach a "terminal status" under a weaker assertion, so this test additionally requires at least
one subtask to land 'done'.

DUAL_LEDGER_PLANNER_ENABLED is intentionally left OFF: BuilderBrain doesn't emit ledger-shaped
completions, and extending the shared simulator double is out of scope for this test.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import orchestrator as O
import platform_core.app_config.paths as paths
import platform_core.simulator.simulation as simulation
from state.task import TaskState

_GRACEFUL_TERMINAL = {"done", "complete", "partial", "failed", "aborted"}
_NON_TERMINAL_SUBTASK_STATUSES = {"pending", "in_progress"}


class TestEpicFlagsCombined(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "tasks").mkdir()
        (self.dir / "control").mkdir()
        self.proj = self.dir / "project"
        self.proj.mkdir()
        (self.proj / "README.md").write_text("pre-existing\n", encoding="utf-8")
        # WORKTREE_ISOLATION_ENABLED needs a real git repo to isolate into.
        subprocess.run(["git", "init"], cwd=self.proj, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "bot@example.com"], cwd=self.proj, check=True)
        subprocess.run(["git", "config", "user.name", "9TO5"], cwd=self.proj, check=True)
        subprocess.run(["git", "add", "README.md"], cwd=self.proj, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.proj, check=True,
                       capture_output=True, text=True)
        self._patches = [
            mock.patch.object(config, "STATE_DIR", self.dir / "tasks"),
            mock.patch.object(config, "CONTROL_DIR", self.dir / "control"),
            mock.patch.object(config, "WEB_DASHBOARD", False),
            mock.patch.object(config, "DISCORD_DASHBOARD", False),
            mock.patch.object(O, "refreshClaudeKnowledge", lambda *a, **k: ""),
            mock.patch.object(O, "startWebDashboard", lambda *a, **k: None),
            mock.patch.object(paths, "BLACKBOARD_DIR", self.dir / "blackboard"),
            mock.patch.object(config, "STEP_RESUME_ENABLED", True),
            mock.patch.object(config, "WORKTREE_ISOLATION_ENABLED", True),
            mock.patch.object(config, "COST_BUDGET_ENABLED", True),
            mock.patch.object(config, "COMPACTION_ENABLED", True),
            mock.patch.object(config, "SEMANTIC_SAFETY_ENABLED", True),
            mock.patch.object(config, "SOCIETY_ENABLED", True),
            mock.patch.object(config, "SOLUTION_FORK_ENABLED", True),
            mock.patch.object(config, "EXECUTION_FABRIC_ENABLED", True),
            mock.patch.object(config, "EXECUTION_BACKEND", "local"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _run(self, n_subtasks=3, parallelism=3):
        st = TaskState.create("build (1) a (2) b (3) c", 1.0)
        st.setElaboratedGoal(st.meta["goal_raw"])
        st.save()
        orch = simulation.buildBuilderOrchestrator(str(self.proj), n_subtasks=n_subtasks)
        return orch.runFull(st, work_dir=str(self.proj), auto_pr=False,
                            control_mode="watch", parallelism=parallelism)

    def test_combined_epic_flags_reach_graceful_terminal_with_progress(self):
        summary = self._run()
        self.assertIn(summary["status"], _GRACEFUL_TERMINAL)
        statuses = {s["status"] for s in summary["subtasks"]}
        # The real regression guard for Epic-5 bugs A/B: a run that silently failed every
        # subtask via crash-containment would still reach a "terminal status" -- this proves
        # at least one subtask was genuinely verified and landed 'done'.
        self.assertIn("done", statuses,
                      f"expected at least one subtask to land 'done', got {statuses}")
        self.assertFalse(statuses & _NON_TERMINAL_SUBTASK_STATUSES,
                         f"subtask(s) left non-terminal at run end: {statuses}")

    def test_no_scaffolding_left_behind(self):
        self._run()
        self.assertFalse((self.proj / ".sc-ctx").exists(),
                         "9to5 left .sc-ctx in the project tree")

