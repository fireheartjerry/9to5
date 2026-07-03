"""Tests for the orchestrator's integration with the centralized WorkflowRegistry.

Acceptance check for subtask st-056: Refactor Orchestrator to Use Workflow Registry.
Exit 0 expected on all tests passing.
"""
from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agents.workflow_resolver import resolveWorkflowDefinition  # noqa: E402
from src.workflow_registry import (  # noqa: E402
    REGISTRY,
    WorkflowRegistry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_reg() -> WorkflowRegistry:
    reg = WorkflowRegistry.__new__(WorkflowRegistry)
    reg._lock = threading.Lock()
    reg._store = {}
    reg._builtin = frozenset()
    return reg


def _inline_spec(name: str = "my-wf") -> dict:
    return {
        "use_workflow": True,
        "workflow_definition": {
            "name": name,
            "description": f"desc of {name}",
            "phases": [
                {
                    "title": "Work",
                    "parallel": False,
                    "agents": [{"label": "doer", "prompt": "do the work", "effort": "default"}],
                }
            ],
            "synthesis": "combine",
        },
    }


def _named_spec(workflow_name: str) -> dict:
    return {
        "use_workflow": True,
        "workflow_name": workflow_name,
    }


# ---------------------------------------------------------------------------
# resolveWorkflowDefinition — named registry lookup
# ---------------------------------------------------------------------------

class TestResolveByName(unittest.TestCase):
    def test_named_shipped_workflow_resolved(self):
        spec = _named_spec("code_review")
        result = resolveWorkflowDefinition(spec)
        self.assertIsNotNone(result)
        self.assertIn("phases", result)

    def test_named_bug_investigation_resolved(self):
        spec = _named_spec("bug_investigation")
        result = resolveWorkflowDefinition(spec)
        self.assertIsNotNone(result)

    def test_named_feature_implementation_resolved(self):
        spec = _named_spec("feature_implementation")
        result = resolveWorkflowDefinition(spec)
        self.assertIsNotNone(result)

    def test_unknown_name_falls_through_to_none_without_inline(self):
        spec = {"use_workflow": True, "workflow_name": "no-such-workflow"}
        result = resolveWorkflowDefinition(spec)
        self.assertIsNone(result)

    def test_unknown_name_falls_through_to_inline(self):
        spec = _inline_spec("fallback-wf")
        spec["workflow_name"] = "does-not-exist"
        result = resolveWorkflowDefinition(spec)
        self.assertIsNotNone(result)
        self.assertEqual(result.get("name"), "fallback-wf")


# ---------------------------------------------------------------------------
# resolveWorkflowDefinition — inline dict path
# ---------------------------------------------------------------------------

class TestResolveInline(unittest.TestCase):
    def test_inline_def_returns_definition(self):
        spec = _inline_spec("test-inline")
        result = resolveWorkflowDefinition(spec)
        self.assertIsNotNone(result)
        self.assertIn("phases", result)

    def test_inline_def_registers_in_registry(self):
        spec = _inline_spec("test-registers")
        resolveWorkflowDefinition(spec)
        self.assertIn("test-registers", REGISTRY.listWorkflows())

    def test_inline_def_retrieval_consistent(self):
        spec = _inline_spec("test-consistent")
        result = resolveWorkflowDefinition(spec)
        from_reg = REGISTRY.getWorkflow("test-consistent")
        self.assertEqual(result, from_reg)

    def test_no_phases_returns_none(self):
        spec = {"use_workflow": True, "workflow_definition": {"name": "empty"}}
        result = resolveWorkflowDefinition(spec)
        self.assertIsNone(result)

    def test_non_dict_returns_none(self):
        result = resolveWorkflowDefinition("not a dict")
        self.assertIsNone(result)

    def test_no_workflow_fields_returns_none(self):
        result = resolveWorkflowDefinition({"use_workflow": False})
        self.assertIsNone(result)

    def test_inline_name_used_as_registry_key(self):
        spec = _inline_spec("my-named-wf")
        resolveWorkflowDefinition(spec)
        self.assertIn("my-named-wf", REGISTRY.listWorkflows())

    def test_unnamed_inline_registered_as_adhoc(self):
        spec = {
            "use_workflow": True,
            "workflow_definition": {
                "phases": [{"title": "P", "agents": [{"label": "a", "prompt": "x", "effort": "default"}]}],
            },
        }
        result = resolveWorkflowDefinition(spec)
        self.assertIsNotNone(result)
        self.assertIn("adhoc", REGISTRY.listWorkflows())


# ---------------------------------------------------------------------------
# Executor _composePrompt integration
# ---------------------------------------------------------------------------

class TestExecutorUsesRegistry(unittest.TestCase):
    """Verify that executor._composePrompt routes workflow rendering through the registry."""

    def _compose(self, spec: dict) -> str:
        from agents.executor import _composePrompt
        return _composePrompt(spec, system_prompt=None, extra=None)

    def test_named_workflow_produces_prompt(self):
        spec = _named_spec("code_review")
        prompt = self._compose(spec)
        self.assertIn("EXECUTE THIS DYNAMIC WORKFLOW", prompt)

    def test_inline_workflow_produces_prompt(self):
        spec = _inline_spec("exec-inline-test")
        prompt = self._compose(spec)
        self.assertIn("do the work", prompt)

    def test_no_workflow_uses_spec_prompt(self):
        spec = {"use_workflow": False, "prompt": "just do the thing"}
        prompt = self._compose(spec)
        self.assertIn("just do the thing", prompt)

    def test_use_workflow_false_skips_registry(self):
        spec = {
            "use_workflow": False,
            "workflow_name": "code_review",
            "prompt": "flat prompt only",
        }
        prompt = self._compose(spec)
        self.assertNotIn("EXECUTE THIS DYNAMIC WORKFLOW", prompt)
        self.assertIn("flat prompt only", prompt)

    def test_workflow_phases_appear_in_prompt(self):
        spec = _inline_spec("exec-phases-test")
        prompt = self._compose(spec)
        self.assertIn("Work", prompt)

    def test_synthesis_appears_in_prompt(self):
        spec = _inline_spec("exec-synth-test")
        prompt = self._compose(spec)
        self.assertIn("combine", prompt)


# ---------------------------------------------------------------------------
# Registry singleton integrity after orchestrator-style usage
# ---------------------------------------------------------------------------

class TestRegistrySingletonIntegrity(unittest.TestCase):
    def test_registry_contains_shipped_workflows_after_resolver_use(self):
        resolveWorkflowDefinition(_inline_spec("integrity-test"))
        for name in ("code_review", "bug_investigation", "feature_implementation"):
            with self.subTest(name=name):
                self.assertIn(name, REGISTRY.listWorkflows())

    def test_registry_is_workflow_registry_instance(self):
        self.assertIsInstance(REGISTRY, WorkflowRegistry)

    def test_concurrent_resolve_does_not_corrupt_registry(self):
        errors: list[str] = []

        def _worker(idx: int) -> None:
            try:
                spec = _inline_spec(f"concurrent-{idx}")
                resolveWorkflowDefinition(spec)
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [], f"concurrent resolver errors: {errors}")
        for i in range(8):
            self.assertIn(f"concurrent-{i}", REGISTRY.listWorkflows())
