"""Tests for Nightclaw's self-ref post-verify quality gate."""
from __future__ import annotations

import unittest
import threading
from unittest import mock

from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin


def _cp(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)


class _ConcreteExecuteMixin(OrchestratorExecuteMixin):
    def _repairVerify(self, subtask, exec_cwd, t0=0.0):  # noqa: ANN001
        return None

    def _resolveClarifications(self, state, subtask, combined, dashboard):  # noqa: ANN001
        return ""


class TestSelfRefQualityGate(unittest.TestCase):
    def test_runs_repo_gates_then_affected_tests(self):
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):  # noqa: ANN001
            calls.append(cmd)
            if cmd[1:] == ["tools\\affected_tests.py"]:
                return _cp(stdout="tests/test_github_pr_gate.py\n")
            return _cp(stdout="ok")

        with mock.patch("platform_core.orchestration.self_ref_gate.subprocess.run", side_effect=fake_run):
            ok, detail = _ConcreteExecuteMixin()._selfRefQualityGate("C:\\9to5")

        self.assertTrue(ok, detail)
        self.assertEqual(calls[0][1:], ["tools\\repo_map.py"])
        self.assertEqual(calls[1][1:], ["tools\\repo_map.py", "--check"])
        self.assertEqual(calls[2][1:], ["validate_workflows.py"])
        self.assertEqual(calls[3][1:], ["tools\\affected_tests.py"])
        self.assertEqual(calls[4][1:4], ["-m", "pytest", "tests/test_github_pr_gate.py"])

    def test_skips_pytest_when_no_affected_tests_map(self):
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):  # noqa: ANN001
            calls.append(cmd)
            return _cp(stdout="")

        with mock.patch("platform_core.orchestration.self_ref_gate.subprocess.run", side_effect=fake_run):
            ok, _ = _ConcreteExecuteMixin()._selfRefQualityGate("C:\\9to5")

        self.assertTrue(ok)
        self.assertEqual(len(calls), 4)

    def test_blocks_on_repo_gate_failure(self):
        failed = _cp(returncode=1, stdout="stale repo map")
        with mock.patch("platform_core.orchestration.self_ref_gate.subprocess.run", return_value=failed) as run:
            ok, detail = _ConcreteExecuteMixin()._selfRefQualityGate("C:\\9to5")

        self.assertFalse(ok)
        self.assertIn("stale repo map", detail)
        self.assertEqual(run.call_count, 1)


class TestRunAttemptVerifyQualityGate(unittest.TestCase):
    def test_self_ref_quality_gate_failure_turns_verify_pass_into_failure(self):
        mixin = _ConcreteExecuteMixin()
        mixin._state_lock = threading.RLock()
        state = mock.MagicMock()
        state.meta = {"is_self_referential": True}
        state.recordVerify = mock.MagicMock()
        dashboard = mock.MagicMock()
        with mock.patch("platform_core.orchestration.execute_mixin.verifier.runVerification",
                        return_value={"passed": True, "cmd": "python test.py", "stdout": "", "stderr": ""}), \
             mock.patch.object(mixin, "_selfRefQualityGate", return_value=(False, "affected tests failed")):
            vresult, passed, _, feedback = mixin._runAttemptVerify(
                state, {"verify": {"cmd": "python test.py"}}, {"stdout": ""},
                "C:\\9to5", {"cmd": "python test.py"}, 0.0, "st-001", "", dashboard, None)

        self.assertFalse(passed)
        self.assertIn("affected tests failed", vresult["stderr"])
        self.assertIn("affected tests failed", feedback)
        state.recordVerify.assert_called_once()
