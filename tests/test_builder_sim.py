"""High-fidelity builder simulation: 9to5 produces REAL files in a chosen project dir and
verifies them for real -- and must NOT leave its .sc-ctx scaffolding behind."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import subprocess

import config
import orchestrator as O
import platform_core.simulator.simulation as simulation
from platform_core.orchestration import github
from state.task import TaskState


class TestBuilderSim(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "tasks").mkdir()
        (self.dir / "control").mkdir()
        self.proj = self.dir / "project"
        self.proj.mkdir()
        (self.proj / "README.md").write_text("pre-existing\n", encoding="utf-8")
        self._patches = [
            mock.patch.object(config, "STATE_DIR", self.dir / "tasks"),
            mock.patch.object(config, "CONTROL_DIR", self.dir / "control"),
            mock.patch.object(config, "WEB_DASHBOARD", False),
            mock.patch.object(config, "DISCORD_DASHBOARD", False),
            mock.patch.object(O, "refreshClaudeKnowledge", lambda *a, **k: ""),
            mock.patch.object(O, "startWebDashboard", lambda *a, **k: None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _run(self, parallelism):
        st = TaskState.create("build (1) a (2) b (3) c", 1.0)
        st.setElaboratedGoal(st.meta["goal_raw"])
        st.save()
        orch = simulation.buildBuilderOrchestrator(str(self.proj), n_subtasks=3)
        return orch.runFull(st, work_dir=str(self.proj), auto_pr=False,
                            control_mode="watch", parallelism=parallelism)

    def test_builder_produces_and_really_verifies_files(self):
        summary = self._run(parallelism=1)
        self.assertEqual(summary["status"], "done")
        self.assertTrue(all(s["verified"] for s in summary["subtasks"]))
        for i in (1, 2, 3):
            self.assertTrue((self.proj / f"feature_{i}.py").exists())
        self.assertTrue((self.proj / "README.md").exists())   # pre-existing file untouched

    def test_no_scaffolding_left_behind(self):
        self._run(parallelism=3)   # parallel mode is what created .sc-ctx
        self.assertFalse((self.proj / ".sc-ctx").exists(), "9to5 left .sc-ctx in the project tree")

    def test_external_repo_run_artifacts_can_be_pr_created(self):
        origin = self.dir / "origin.git"
        subprocess.run(["git", "init", "--bare", str(origin)], check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "init"], cwd=self.proj, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "bot@example.com"], cwd=self.proj, check=True)
        subprocess.run(["git", "config", "user.name", "9TO5"], cwd=self.proj, check=True)
        subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=self.proj, check=True)
        subprocess.run(["git", "add", "README.md"], cwd=self.proj, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.proj, check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "push", "-u", "origin", "HEAD:main"], cwd=self.proj, check=True,
                       capture_output=True, text=True)

        st = TaskState.create("build one external feature", 1.0)
        st.setElaboratedGoal(st.meta["goal_raw"])
        st.save()
        orch = simulation.buildBuilderOrchestrator(str(self.proj), n_subtasks=1)
        summary = orch.runFull(st, work_dir=str(self.proj), auto_pr=False,
                               control_mode="watch", parallelism=1)
        self.assertEqual(summary["status"], "done")
        self.assertFalse(st.meta.get("is_self_referential"))
        self.assertTrue((self.proj / "feature_1.py").exists())
        self.assertFalse((self.proj / ".sc-ctx").exists())
        self.assertFalse((self.proj / "CLAUDE.md").exists())

        real_run = subprocess.run

        def fake_run(cmd, **kwargs):  # noqa: ANN001
            if cmd[:3] == ["gh", "pr", "create"]:
                return mock.Mock(returncode=0, stdout="https://github.com/acme/repo/pull/7\n", stderr="")
            return real_run(cmd, **kwargs)

        with mock.patch("platform_core.orchestration.github.subprocess.run", side_effect=fake_run), \
                mock.patch("platform_core.orchestration.github.shutil.which", return_value="gh"):
            pr = github.createPullRequest(st, str(self.proj))

        self.assertEqual(pr.get("url"), "https://github.com/acme/repo/pull/7")
        head = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.proj,
                              check=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(head, f"9to5/{st.task_id[:8]}")


if __name__ == "__main__":
    unittest.main()
