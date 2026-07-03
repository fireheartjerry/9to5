"""Tests for Nightclaw's self-ref post-verify quality gate."""
from __future__ import annotations

import unittest
import threading
from unittest import mock

from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin
from platform_core.orchestration.validation_cache import ValidationResult


class _ConcreteExecuteMixin(OrchestratorExecuteMixin):
    def _repairVerify(self, subtask, exec_cwd, t0=0.0):  # noqa: ANN001
        return None

    def _resolveClarifications(self, state, subtask, combined, dashboard):  # noqa: ANN001
        return ""


class TestSelfRefQualityGate(unittest.TestCase):
    def test_runs_repo_gates_then_affected_tests(self):
        result = ValidationResult(True, "ok", commands=[["python", "tools\\repo_map.py"]])
        with mock.patch("platform_core.orchestration.self_ref_gate.run_validation_suite",
                        return_value=result) as suite:
            ok, detail = _ConcreteExecuteMixin()._selfRefQualityGate("C:\\9to5")

        self.assertTrue(ok, detail)
        suite.assert_called_once_with("self_ref_incremental", "C:\\9to5")

    def test_skips_pytest_when_no_affected_tests_map(self):
        result = ValidationResult(True, "no affected tests", cached=True)
        with mock.patch("platform_core.orchestration.self_ref_gate.run_validation_suite",
                        return_value=result):
            ok, _ = _ConcreteExecuteMixin()._selfRefQualityGate("C:\\9to5")

        self.assertTrue(ok)

    def test_blocks_on_repo_gate_failure(self):
        failed = ValidationResult(False, "stale repo map")
        with mock.patch("platform_core.orchestration.self_ref_gate.run_validation_suite",
                        return_value=failed) as suite:
            ok, detail = _ConcreteExecuteMixin()._selfRefQualityGate("C:\\9to5")

        self.assertFalse(ok)
        self.assertIn("stale repo map", detail)
        suite.assert_called_once_with("self_ref_incremental", "C:\\9to5")


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
