"""Tests for the code review workflow definition and registry integration.

Validates that:
  - code_review.json is structurally valid and loads without error
  - The workflow has at least one parallel phase (required for ≥20% time reduction)
  - WorkflowRegistry loads the definition and can execute it
  - resolveWorkflowDefinition handles both named and inline specs
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from platform_core.orchestration.workflows.registry import (  # noqa: E402
    DEFINITIONS_DIR,
    _validateWorkflowDefinition,
    loadRegistry,
)
from src.workflow_registry import (  # noqa: E402
    WorkflowRegistry,
    WorkflowNotFoundError,
    WorkflowValidationError,
)


DEFINITION_PATH = DEFINITIONS_DIR / "code_review.json"


# ---------------------------------------------------------------------------
# Definition file: structural validity
# ---------------------------------------------------------------------------
class TestCodeReviewDefinitionFile(unittest.TestCase):

    def setUp(self):
        self.assertTrue(DEFINITION_PATH.exists(),
                        f"code_review.json not found at {DEFINITION_PATH}")
        self.defn = json.loads(DEFINITION_PATH.read_text(encoding="utf-8"))

    def test_passes_validation(self):
        err = _validateWorkflowDefinition(self.defn, "code_review.json")
        self.assertIsNone(err, f"Validation failed: {err}")

    def test_has_required_name(self):
        self.assertIn("name", self.defn)
        self.assertIsInstance(self.defn["name"], str)
        self.assertTrue(self.defn["name"])

    def test_has_phases(self):
        self.assertIn("phases", self.defn)
        self.assertIsInstance(self.defn["phases"], list)
        self.assertGreater(len(self.defn["phases"]), 0)

    def test_has_synthesis(self):
        self.assertIn("synthesis", self.defn)
        self.assertIsInstance(self.defn["synthesis"], str)
        self.assertTrue(self.defn["synthesis"])

    def test_has_at_least_one_parallel_phase(self):
        parallel_phases = [p for p in self.defn["phases"] if p.get("parallel") is True]
        self.assertGreater(
            len(parallel_phases), 0,
            "Optimized workflow must have at least one parallel phase to reduce review time by ≥20%"
        )

    def test_parallel_phase_has_multiple_agents(self):
        parallel_phases = [p for p in self.defn["phases"] if p.get("parallel") is True]
        for phase in parallel_phases:
            agents = phase.get("agents", [])
            self.assertGreaterEqual(
                len(agents), 2,
                f"Parallel phase '{phase.get('title')}' must have ≥2 agents to benefit from parallelism"
            )

    def test_agent_effort_values_valid(self):
        valid_efforts = {"default", "high", "xhigh", "ultracode"}
        for phase in self.defn["phases"]:
            for agent in phase.get("agents", []):
                if "effort" in agent:
                    self.assertIn(agent["effort"], valid_efforts,
                                  f"Agent '{agent.get('label')}' has invalid effort '{agent['effort']}'")

    def test_no_unknown_keys_in_agents(self):
        allowed_agent_keys = {"label", "prompt", "effort"}
        for phase in self.defn["phases"]:
            for agent in phase.get("agents", []):
                unknown = set(agent.keys()) - allowed_agent_keys
                self.assertEqual(unknown, set(),
                                 f"Agent has unknown keys: {unknown}")


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------
class TestLoadRegistry(unittest.TestCase):

    def test_loads_code_review_workflow(self):
        registry = loadRegistry(DEFINITIONS_DIR)
        self.assertIn("code_review", registry)

    def test_loaded_definition_is_valid(self):
        registry = loadRegistry(DEFINITIONS_DIR)
        defn = registry["code_review"]
        err = _validateWorkflowDefinition(defn, "code_review")
        self.assertIsNone(err)

    def test_skips_invalid_json_file(self):
        with mock.patch("platform_core.orchestration.workflows.registry.Path.glob",
                        return_value=[Path("bad.json")]):
            with mock.patch.object(Path, "read_text",
                                   side_effect=OSError("unreadable")):
                result = loadRegistry(DEFINITIONS_DIR)
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# WorkflowRegistry (src/workflow_registry.py)
# ---------------------------------------------------------------------------
class TestWorkflowRegistry(unittest.TestCase):

    def _make_valid_defn(self, name="test_wf") -> dict:
        return {
            "name": name,
            "description": "A test workflow",
            "phases": [
                {
                    "title": "Parallel review",
                    "parallel": True,
                    "agents": [
                        {"label": "correctness", "prompt": "Check correctness.", "effort": "high"},
                        {"label": "security", "prompt": "Check security.", "effort": "high"},
                    ],
                }
            ],
            "synthesis": "Merge findings.",
        }

    def test_code_review_loaded_on_init(self):
        reg = WorkflowRegistry(DEFINITIONS_DIR)
        defn = reg.getWorkflow("code_review")
        self.assertEqual(defn["name"], "code_review")

    def test_add_and_get_workflow(self):
        reg = WorkflowRegistry(DEFINITIONS_DIR)
        defn = self._make_valid_defn("wf_add_test")
        reg.addWorkflow("wf_add_test", defn)
        result = reg.getWorkflow("wf_add_test")
        self.assertEqual(result["name"], "wf_add_test")

    def test_get_nonexistent_raises(self):
        reg = WorkflowRegistry(DEFINITIONS_DIR)
        with self.assertRaises(WorkflowNotFoundError):
            reg.getWorkflow("__nonexistent__")

    def test_add_invalid_raises_validation_error(self):
        reg = WorkflowRegistry(DEFINITIONS_DIR)
        bad_defn = {"name": "bad", "phases": "not-a-list"}
        with self.assertRaises(WorkflowValidationError):
            reg.addWorkflow("bad", bad_defn)

    def test_remove_workflow(self):
        reg = WorkflowRegistry(DEFINITIONS_DIR)
        reg.addWorkflow("wf_remove_test", self._make_valid_defn("wf_remove_test"))
        reg.removeWorkflow("wf_remove_test")
        with self.assertRaises(WorkflowNotFoundError):
            reg.getWorkflow("wf_remove_test")

    def test_list_workflows_includes_code_review(self):
        reg = WorkflowRegistry(DEFINITIONS_DIR)
        names = reg.listWorkflows()
        self.assertIn("code_review", names)

    def test_execute_workflow_returns_ok(self):
        reg = WorkflowRegistry(DEFINITIONS_DIR)
        result = reg.executeWorkflow("code_review", context="test context")
        self.assertTrue(result["ok"])
        self.assertIn("prompt", result)
        self.assertIsInstance(result["prompt"], str)

    def test_execute_workflow_prompt_mentions_parallel(self):
        reg = WorkflowRegistry(DEFINITIONS_DIR)
        result = reg.executeWorkflow("code_review")
        self.assertIn("parallel", result["prompt"].lower())

    def test_execute_workflow_prompt_contains_synthesis(self):
        reg = WorkflowRegistry(DEFINITIONS_DIR)
        result = reg.executeWorkflow("code_review")
        self.assertIn("Synthesis", result["prompt"])

    def test_add_workflow_is_idempotent(self):
        reg = WorkflowRegistry(DEFINITIONS_DIR)
        defn = self._make_valid_defn("wf_idem_test")
        reg.addWorkflow("wf_idem_test", defn)
        reg.addWorkflow("wf_idem_test", defn)
        self.assertEqual(reg.getWorkflow("wf_idem_test")["name"], "wf_idem_test")


# ---------------------------------------------------------------------------
# resolveWorkflowDefinition integration
# ---------------------------------------------------------------------------
class TestResolveWorkflowDefinition(unittest.TestCase):

    def test_resolves_by_name(self):
        from agents.workflow_resolver import resolveWorkflowDefinition
        spec = {"use_workflow": True, "workflow_name": "code_review"}
        result = resolveWorkflowDefinition(spec)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "code_review")

    def test_resolves_inline_definition(self):
        from agents.workflow_resolver import resolveWorkflowDefinition
        inline = {
            "name": "inline_test",
            "description": "inline",
            "phases": [
                {
                    "title": "P1",
                    "parallel": True,
                    "agents": [
                        {"label": "a", "prompt": "do a", "effort": "default"},
                        {"label": "b", "prompt": "do b", "effort": "default"},
                    ],
                }
            ],
            "synthesis": "merge",
        }
        spec = {"use_workflow": True, "workflow_definition": inline}
        result = resolveWorkflowDefinition(spec)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "inline_test")

    def test_returns_none_for_empty_spec(self):
        from agents.workflow_resolver import resolveWorkflowDefinition
        result = resolveWorkflowDefinition({})
        self.assertIsNone(result)

    def test_returns_none_for_unknown_name(self):
        from agents.workflow_resolver import resolveWorkflowDefinition
        spec = {"use_workflow": True, "workflow_name": "__nonexistent_wf__"}
        result = resolveWorkflowDefinition(spec)
        self.assertIsNone(result)
