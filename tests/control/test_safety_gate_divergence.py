"""TDD tests for fix #14: safety_gate must refuse to bless code the run never executed.

When ``code_diverged=True`` (Task 5.2 set this because selfmod edited on-disk files
mid-run while the orchestrator kept running pre-edit bytecode), the gate must NOT call
the test runner and must NOT report the run as verified -- because the tests would be
exercising the edited code, not the code this process actually ran.
"""
import unittest
from unittest import mock

import config
import selfmod


class TestGateHonorsDivergence(unittest.TestCase):
    """safety_gate must short-circuit when code_diverged=True."""

    def test_diverged_run_is_reported_unverified(self):
        """When code diverged mid-run, gate must NOT claim edits were verified."""
        result = selfmod.safety_gate(
            "/fake/work_dir",
            is_self_referential=True,
            code_diverged=True,
            test_runner=lambda d: (True, "all green"),  # would report green
        )
        # Must NOT be ran=True (that would mean tests ran and blessed the change)
        self.assertFalse(result.get("ran", True),
                         f"Expected ran=False, got: {result}")
        # Reason must mention divergence
        reason = (result.get("reason") or "").lower()
        self.assertIn("diverg", reason,
                      f"Expected 'diverg' in reason, got: {reason!r}")

    def test_diverged_run_does_not_call_test_runner(self):
        """The test runner must NOT be invoked when code_diverged=True."""
        runner = mock.Mock(return_value=(True, "green"))
        selfmod.safety_gate(
            "/fake/work_dir",
            is_self_referential=True,
            code_diverged=True,
            test_runner=runner,
        )
        runner.assert_not_called()

    def test_non_diverged_run_unaffected_noop(self):
        """Without divergence and no core changes, gate still returns no_core_changes noop."""
        # We need SELFMOD_ALLOW_CORE=True and is_self_referential=True for the gate to
        # even look at core files. With no actual work_dir that has git, it should
        # return no_core_changes (core_files_changed returns [] on error too).
        with mock.patch.object(config, "SELFMOD_ALLOW_CORE", True):
            result = selfmod.safety_gate(
                "/nonexistent/path",
                is_self_referential=True,
                code_diverged=False,
                test_runner=lambda d: (True, "green"),
            )
        # Without divergence the gate proceeds normally -- no diverge short-circuit
        reason = (result.get("reason") or "").lower()
        self.assertNotIn("diverg", reason,
                         f"Non-diverged run should not mention diverge, got: {reason!r}")

    def test_non_diverged_run_default_param(self):
        """code_diverged defaults to False -- existing callers must not break."""
        with mock.patch.object(config, "SELFMOD_ALLOW_CORE", True):
            result = selfmod.safety_gate(
                "/nonexistent/path",
                is_self_referential=True,
                test_runner=lambda d: (True, "green"),
                # code_diverged NOT passed -- tests existing callers
            )
        # Should not diverge-short-circuit (will be 'no_core_changes' or similar)
        reason = (result.get("reason") or "").lower()
        self.assertNotIn("diverg", reason,
                         f"Default (non-diverged) must not mention diverge, got: {reason!r}")

    def test_diverged_takes_priority_over_not_enabled(self):
        """code_diverged short-circuit fires even when SELFMOD_ALLOW_CORE is False
        -- a diverged run is never verified regardless of other flags."""
        with mock.patch.object(config, "SELFMOD_ALLOW_CORE", False):
            result = selfmod.safety_gate(
                "/fake/work_dir",
                is_self_referential=True,
                code_diverged=True,
                test_runner=lambda d: (True, "green"),
            )
        self.assertFalse(result.get("ran", True))
        reason = (result.get("reason") or "").lower()
        self.assertIn("diverg", reason)
