"""Staging acceptance tests -- Deploy Changes to Staging Environment.

Validates that the workflow registry and the staging validator gate are
consistently functional before promotion to production.

Run:
    python C:/9to5/tests/test_staging_changes.py
    python -m pytest tests/test_staging_changes.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# 1. Workflow registry
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


# ---------------------------------------------------------------------------
# 2. Staging validator gate
# ---------------------------------------------------------------------------

class TestStagingValidatorGate(unittest.TestCase):
    def test_staging_validator_passes(self):
        import platform_core.ops.staging_validator as staging_validator
        result = staging_validator.main(quiet=True)
        self.assertEqual(result, 0, "staging_validator reported gate failures")
