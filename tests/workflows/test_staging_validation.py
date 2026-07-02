"""Acceptance test: staging environment validation.

Verifies that:
1. ops.staging_validator is importable and exposes validate() / main().
2. All staging gates pass (imports, CI workflow, validate_workflows.py script).
3. main() exits 0 when run from CLI.

Run:
    python tests/test_staging_validation.py
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestStagingValidatorModule(unittest.TestCase):
    """platform_core.ops.staging_validator exists and exposes the required API."""

    def test_module_importable(self):
        mod = importlib.import_module("platform_core.ops.staging_validator")
        self.assertIsNotNone(mod)

    def test_validate_callable(self):
        from platform_core.ops.staging_validator import validate
        self.assertTrue(callable(validate))

    def test_main_callable(self):
        from platform_core.ops.staging_validator import main
        self.assertTrue(callable(main))


class TestStagingGates(unittest.TestCase):
    """All staging gates defined in staging_validator must pass."""

    def setUp(self):
        from platform_core.ops.staging_validator import validate
        self._results = validate()

    def test_gates_non_empty(self):
        self.assertGreater(len(self._results), 0, "validate() must return at least one gate result")

    def test_all_gates_pass(self):
        failed = [r for r in self._results if not r["passed"]]
        if failed:
            details = "\n".join(f"  [{r['gate']}] {r['detail']}" for r in failed)
            self.fail(f"Staging gates failed:\n{details}")

    def test_gate_results_have_required_keys(self):
        for r in self._results:
            self.assertIn("gate", r, f"gate result missing 'gate' key: {r}")
            self.assertIn("passed", r, f"gate result missing 'passed' key: {r}")
            self.assertIn("detail", r, f"gate result missing 'detail' key: {r}")

    def test_import_gates_present(self):
        gate_names = {r["gate"] for r in self._results}
        self.assertIn("import:config", gate_names)
        self.assertIn("import:platform_core.ops.health", gate_names)
        self.assertIn("import:agents.verifier", gate_names)

    def test_ci_workflow_gate_present(self):
        gate_names = {r["gate"] for r in self._results}
        self.assertIn("ci_workflow:exists", gate_names)

    def test_validate_workflows_script_gate_present(self):
        gate_names = {r["gate"] for r in self._results}
        self.assertIn("validate_workflows_script:exists", gate_names)


class TestStagingMainExitCode(unittest.TestCase):
    """main() returns 0 when all gates pass."""

    def test_main_returns_zero(self):
        from platform_core.ops.staging_validator import main
        exit_code = main(quiet=True)
        self.assertEqual(exit_code, 0, "staging_validator.main() must return 0 in a healthy repo")
