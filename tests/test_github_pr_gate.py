"""Tests for PR gate and staging behavior in platform_core.orchestration.github."""
from __future__ import annotations

import unittest
from unittest import mock

from platform_core.orchestration import github


def _cp(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)


def _state():
    state = mock.MagicMock()
    state.task_id = "abcdef12-0000"
    state.meta = {"goal_raw": "ship focused change", "is_self_referential": True}
    return state


class TestPrePrSuiteGate(unittest.TestCase):
    def test_self_ref_gate_runs_repo_map_before_checks_and_fast_lane(self):
        passed = _cp(stdout="ok")
        with mock.patch("platform_core.orchestration.github.subprocess.run", return_value=passed) as run:
            ok, _ = github._prePrSuiteGate(_state(), "C:\\9to5")
        self.assertTrue(ok)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][1:], ["tools\\repo_map.py"])
        self.assertEqual(commands[1][1:], ["tools\\repo_map.py", "--check"])
        self.assertEqual(commands[2][1:], ["validate_workflows.py"])
        self.assertEqual(commands[3][1:4], ["-m", "pytest", "-m"])
        self.assertIn("not slow", commands[3])

    def test_self_ref_gate_blocks_on_first_failure(self):
        failed = _cp(returncode=1, stdout="repo map stale")
        with mock.patch("platform_core.orchestration.github.subprocess.run", return_value=failed) as run:
            ok, detail = github._prePrSuiteGate(_state(), "C:\\9to5")
        self.assertFalse(ok)
        self.assertIn("repo map stale", detail)
        self.assertEqual(run.call_count, 1)


class TestCreatePullRequestStaging(unittest.TestCase):
    def test_staging_excludes_scratch_and_python_cache_files(self):
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):  # noqa: ANN001
            calls.append(cmd)
            if cmd[:2] == ["git", "rev-parse"]:
                return _cp(stdout="true\n")
            if cmd[:2] == ["git", "ls-files"]:
                return _cp(returncode=1)
            if cmd[:2] == ["git", "commit"]:
                return _cp(stdout="committed")
            if cmd[:2] == ["git", "push"]:
                return _cp()
            if cmd[:3] == ["gh", "pr", "create"]:
                return _cp(stdout="https://github.com/acme/repo/pull/1\n")
            return _cp()

        with mock.patch("platform_core.orchestration.github.subprocess.run", side_effect=fake_run):
            result = github.createPullRequest(_state(), "C:\\9to5")

        self.assertTrue(result["ok"])
        add_cmd = next(cmd for cmd in calls if cmd[:3] == ["git", "add", "-A"])
        self.assertIn(":(exclude).sc-ctx", add_cmd)
        self.assertIn(":(exclude)**/__pycache__/**", add_cmd)
        self.assertIn(":(exclude)**/*.pyc", add_cmd)


if __name__ == "__main__":
    unittest.main()
