"""Tests for Nightclaw's self-ref post-verify quality gate."""

from __future__ import annotations

import unittest
import threading
from unittest import mock

from agents.verification import Receipt, VResult, Verdict
from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin
from platform_core.orchestration.validation_cache import ValidationResult


def _vresult_with_diff(diff_files, **overrides):
    """A VResult whose typed Receipt records the subtask's own changed-file set."""
    mapping = {"passed": True, "cmd": "python test.py", "stdout": "", "stderr": ""}
    mapping.update(overrides)
    receipt = Receipt(
        verdict=Verdict.PASS,
        cmd=("python", "test.py"),
        rc=0,
        expect_mode="exit_zero",
        matched=(),
        missing=(),
        diff_files=tuple(diff_files),
        duration_s=0.0,
        failure_feedback="",
    )
    return VResult(receipt, mapping)


class _ConcreteExecuteMixin(OrchestratorExecuteMixin):
    def _repairVerify(self, subtask, exec_cwd, t0=0.0):  # noqa: ANN001
        return None

    def _resolveClarifications(self, state, subtask, combined, dashboard):  # noqa: ANN001
        return ""


class TestSelfRefQualityGate(unittest.TestCase):
    def test_runs_repo_gates_then_affected_tests(self):
        result = ValidationResult(True, "ok", commands=[["python", "tools\\repo_map.py"]])
        with mock.patch(
            "platform_core.orchestration.self_ref_gate.run_validation_suite", return_value=result
        ) as suite:
            ok, detail = _ConcreteExecuteMixin()._selfRefQualityGate("C:\\9to5")

        self.assertTrue(ok, detail)
        suite.assert_called_once_with("self_ref_incremental", "C:\\9to5", changed_files=None)

    def test_scopes_affected_tests_to_subtask_changed_files(self):
        """When the subtask's own changed files are threaded in, they are passed down so the
        affected-tests resolution is scoped to the subtask -- not the cumulative repo diff."""
        result = ValidationResult(True, "ok")
        with mock.patch(
            "platform_core.orchestration.self_ref_gate.run_validation_suite", return_value=result
        ) as suite:
            ok, _ = _ConcreteExecuteMixin()._selfRefQualityGate("C:\\9to5", changed_files=["pkg/mod.py"])

        self.assertTrue(ok)
        suite.assert_called_once_with("self_ref_incremental", "C:\\9to5", changed_files=["pkg/mod.py"])

    def test_skips_pytest_when_no_affected_tests_map(self):
        result = ValidationResult(True, "no affected tests", cached=True)
        with mock.patch(
            "platform_core.orchestration.self_ref_gate.run_validation_suite", return_value=result
        ):
            ok, _ = _ConcreteExecuteMixin()._selfRefQualityGate("C:\\9to5")

        self.assertTrue(ok)

    def test_blocks_on_repo_gate_failure(self):
        failed = ValidationResult(False, "stale repo map")
        with mock.patch(
            "platform_core.orchestration.self_ref_gate.run_validation_suite", return_value=failed
        ) as suite:
            ok, detail = _ConcreteExecuteMixin()._selfRefQualityGate("C:\\9to5")

        self.assertFalse(ok)
        self.assertIn("stale repo map", detail)
        suite.assert_called_once_with("self_ref_incremental", "C:\\9to5", changed_files=None)


class TestRunAttemptVerifyQualityGate(unittest.TestCase):
    def test_self_ref_quality_gate_failure_turns_verify_pass_into_failure(self):
        mixin = _ConcreteExecuteMixin()
        mixin._state_lock = threading.RLock()
        state = mock.MagicMock()
        state.meta = {"is_self_referential": True}
        state.recordVerify = mock.MagicMock()
        dashboard = mock.MagicMock()
        with (
            mock.patch(
                "platform_core.orchestration.execute_mixin.verifier.runVerification",
                return_value=_vresult_with_diff(["pkg/mod.py"]),
            ),
            mock.patch.object(
                mixin, "_selfRefQualityGate", return_value=(False, "affected tests failed")
            ) as gate,
        ):
            vresult, passed, _, feedback = mixin._runAttemptVerify(
                state,
                {"verify": {"cmd": "python test.py"}},
                {"stdout": ""},
                "C:\\9to5",
                {"cmd": "python test.py"},
                0.0,
                "st-001",
                "",
                dashboard,
                None,
            )

        self.assertFalse(passed)
        self.assertIn("affected tests failed", vresult["stderr"])
        self.assertIn("affected tests failed", feedback)
        state.recordVerify.assert_called_once()
        # The gate must be scoped to the subtask's OWN changed files, not the cumulative repo diff.
        gate.assert_called_once_with("C:\\9to5", changed_files=["pkg/mod.py"])

    def test_passing_subtask_not_downgraded_when_no_diff_files(self):
        """If the Receipt records no changed files, we cannot scope the gate to this subtask's
        change -- so a passing verify must be left alone (fail-open), NOT flipped to FAIL by an
        unrelated red test elsewhere in the repo."""
        mixin = _ConcreteExecuteMixin()
        mixin._state_lock = threading.RLock()
        state = mock.MagicMock()
        state.meta = {"is_self_referential": True}
        state.recordVerify = mock.MagicMock()
        dashboard = mock.MagicMock()
        with (
            mock.patch(
                "platform_core.orchestration.execute_mixin.verifier.runVerification",
                return_value=_vresult_with_diff([]),  # empty diff_files
            ),
            mock.patch.object(
                mixin, "_selfRefQualityGate", return_value=(False, "unrelated red test")
            ) as gate,
        ):
            _vresult, passed, *_ = mixin._runAttemptVerify(
                state,
                {"verify": {"cmd": "python test.py"}},
                {"stdout": ""},
                "C:\\9to5",
                {"cmd": "python test.py"},
                0.0,
                "st-001",
                "",
                dashboard,
                None,
            )

        self.assertTrue(passed, "empty diff_files must not reintroduce repo-wide doom")
        gate.assert_not_called()

    def test_non_py_diff_files_are_filtered_before_scoping(self):
        """Only .py files map to affected tests; a non-.py-only change means nothing to scope, so
        the passing verify is left alone rather than falling back to the cumulative diff."""
        mixin = _ConcreteExecuteMixin()
        mixin._state_lock = threading.RLock()
        state = mock.MagicMock()
        state.meta = {"is_self_referential": True}
        state.recordVerify = mock.MagicMock()
        dashboard = mock.MagicMock()
        with (
            mock.patch(
                "platform_core.orchestration.execute_mixin.verifier.runVerification",
                return_value=_vresult_with_diff(["docs/readme.md", "notes.txt"]),
            ),
            mock.patch.object(
                mixin, "_selfRefQualityGate", return_value=(False, "unrelated red test")
            ) as gate,
        ):
            _vresult, passed, *_ = mixin._runAttemptVerify(
                state,
                {"verify": {"cmd": "python test.py"}},
                {"stdout": ""},
                "C:\\9to5",
                {"cmd": "python test.py"},
                0.0,
                "st-001",
                "",
                dashboard,
                None,
            )

        self.assertTrue(passed)
        gate.assert_not_called()
