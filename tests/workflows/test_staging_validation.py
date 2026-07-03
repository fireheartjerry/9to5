"""Acceptance test: staging environment validation.

Verifies that:
1. ops.staging_validator is importable and exposes validate() / main().
2. All staging gates pass (imports, CI workflow, validate_workflows.py script).
3. main() exits 0 when run from CLI.
4. The workflow registry (src.workflow_registry) and workflow resolver
   (agents.workflow_resolver) that staging_validator's import gates depend on
   are themselves functional (CRUD, resolution, execution).

Run:
    python tests/test_staging_validation.py

Merged from test_staging_changes.py ("Deploy Changes to Staging Environment"
acceptance test) as part of tests/workflows/ file-sprawl cleanup -- both files
covered the same staging-promotion acceptance concern.
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


# ---------------------------------------------------------------------------
# 1. Workflow registry (dependency of the import gates above)
# ---------------------------------------------------------------------------

class TestWorkflowRegistryImports(unittest.TestCase):
    def test_registry_module_imports(self):
        from src.workflow_registry import WorkflowRegistry, WorkflowNotFoundError, WorkflowValidationError, REGISTRY
        self.assertIsInstance(REGISTRY, WorkflowRegistry)

    def test_workflow_resolver_imports(self):
        from agents.workflow_resolver import resolveWorkflowDefinition
        self.assertIsNotNone(resolveWorkflowDefinition)


class TestWorkflowRegistryCRUD(unittest.TestCase):
    def setUp(self):
        from src.workflow_registry import WorkflowRegistry
        self._reg = WorkflowRegistry.__new__(WorkflowRegistry)
        import threading
        self._reg._lock = threading.Lock()
        self._reg._store = {}
        self._reg._builtin = frozenset()

    def _wf(self, name: str = "staging-test") -> dict:
        return {
            "name": name,
            "phases": [
                {
                    "title": "Phase 1",
                    "parallel": False,
                    "agents": [{"label": "a", "effort": "default", "prompt": "do X"}],
                }
            ],
        }

    def test_add_and_get_workflow(self):
        self._reg.addWorkflow("staging-test", self._wf())
        result = self._reg.getWorkflow("staging-test")
        self.assertEqual(result["name"], "staging-test")

    def test_list_workflows(self):
        self._reg.addWorkflow("wf-a", self._wf("wf-a"))
        self._reg.addWorkflow("wf-b", self._wf("wf-b"))
        names = self._reg.listWorkflows()
        self.assertIn("wf-a", names)
        self.assertIn("wf-b", names)

    def test_remove_workflow(self):
        from src.workflow_registry import WorkflowNotFoundError
        self._reg.addWorkflow("wf-rm", self._wf("wf-rm"))
        self._reg.removeWorkflow("wf-rm")
        with self.assertRaises(WorkflowNotFoundError):
            self._reg.getWorkflow("wf-rm")

    def test_get_missing_raises(self):
        from src.workflow_registry import WorkflowNotFoundError
        with self.assertRaises(WorkflowNotFoundError):
            self._reg.getWorkflow("does-not-exist")

    def test_invalid_definition_raises(self):
        from src.workflow_registry import WorkflowValidationError
        # Unknown key in the root dict triggers validation failure.
        with self.assertRaises(WorkflowValidationError):
            self._reg.addWorkflow("bad", {"unknown_key": True})

    def test_execute_workflow_returns_prompt(self):
        self._reg.addWorkflow("exec-test", self._wf("exec-test"))
        out = self._reg.executeWorkflow("exec-test", context="staging")
        self.assertTrue(out["ok"])
        self.assertIn("Phase 1", out["prompt"])
        self.assertIn("staging", out["prompt"])


class TestWorkflowResolver(unittest.TestCase):
    def test_none_spec_returns_none(self):
        from agents.workflow_resolver import resolveWorkflowDefinition
        self.assertIsNone(resolveWorkflowDefinition(None))

    def test_empty_spec_returns_none(self):
        from agents.workflow_resolver import resolveWorkflowDefinition
        self.assertIsNone(resolveWorkflowDefinition({}))

    def test_inline_definition_resolves(self):
        from agents.workflow_resolver import resolveWorkflowDefinition
        spec = {
            "workflow_definition": {
                "name": "inline-wf",
                "phases": [
                    {"title": "P1", "agents": [{"label": "x", "effort": "default", "prompt": "y"}]}
                ],
            }
        }
        result = resolveWorkflowDefinition(spec)
        self.assertIsNotNone(result)
        self.assertIn("phases", result)
