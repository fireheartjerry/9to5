"""tests/test_feature_implementation.py -- Validate the refined feature_implementation workflow.

Verifies:
  - Workflow JSON is valid and loads via WorkflowRegistry.
  - Phase 1 (Design) is parallel (design + test-design concurrent).
  - Phase 2 (Implement and verify) is now parallel (implement + security-review concurrent).
  - Phase 3 (Test and document) is now parallel (test + doc-update concurrent).
  - speedup_model documents ≥20% wall-clock reduction (ratio ≤ 0.80).
  - executeWorkflow produces a valid prompt string.
"""
import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_DEFN_PATH = _ROOT / "workflows" / "definitions" / "feature_implementation.json"


def _load_defn() -> dict:
    with _DEFN_PATH.open() as f:
        return json.load(f)


class TestFeatureImplementationJson(unittest.TestCase):
    """Structural checks on the raw JSON definition."""

    def setUp(self):
        self.defn = _load_defn()

    def test_file_exists(self):
        self.assertTrue(_DEFN_PATH.exists(), f"Missing: {_DEFN_PATH}")

    def test_name_field(self):
        self.assertEqual(self.defn["name"], "feature_implementation")

    def test_has_three_phases(self):
        self.assertEqual(len(self.defn["phases"]), 3)

    def test_has_synthesis(self):
        self.assertIn("synthesis", self.defn)
        self.assertIsInstance(self.defn["synthesis"], str)
        self.assertTrue(self.defn["synthesis"].strip())

    # ------------------------------------------------------------------
    # Phase 1: Design — parallel (design + test-design)
    # ------------------------------------------------------------------

    def test_phase1_is_parallel(self):
        phase = self.defn["phases"][0]
        self.assertTrue(phase.get("parallel"), "Phase 1 (Design) must be parallel")

    def test_phase1_has_design_agent(self):
        labels = {a["label"] for a in self.defn["phases"][0]["agents"]}
        self.assertIn("design", labels)

    def test_phase1_has_test_design_agent(self):
        labels = {a["label"] for a in self.defn["phases"][0]["agents"]}
        self.assertIn("test-design", labels)

    def test_phase1_has_two_agents(self):
        self.assertEqual(len(self.defn["phases"][0]["agents"]), 2)

    # ------------------------------------------------------------------
    # Phase 2: Implement and verify — now PARALLEL
    # ------------------------------------------------------------------

    def test_phase2_is_parallel(self):
        phase = self.defn["phases"][1]
        self.assertTrue(phase.get("parallel"), "Phase 2 must be parallel for concurrent speedup")

    def test_phase2_has_implement_agent(self):
        labels = {a["label"] for a in self.defn["phases"][1]["agents"]}
        self.assertIn("implement", labels)

    def test_phase2_has_security_review_agent(self):
        labels = {a["label"] for a in self.defn["phases"][1]["agents"]}
        self.assertIn("security-review", labels)

    def test_phase2_has_two_agents(self):
        self.assertEqual(len(self.defn["phases"][1]["agents"]), 2)

    # ------------------------------------------------------------------
    # Phase 3: Test and document — now PARALLEL
    # ------------------------------------------------------------------

    def test_phase3_is_parallel(self):
        phase = self.defn["phases"][2]
        self.assertTrue(phase.get("parallel"), "Phase 3 must be parallel for concurrent speedup")

    def test_phase3_has_test_agent(self):
        labels = {a["label"] for a in self.defn["phases"][2]["agents"]}
        self.assertIn("test", labels)

    def test_phase3_has_doc_update_agent(self):
        labels = {a["label"] for a in self.defn["phases"][2]["agents"]}
        self.assertIn("doc-update", labels)

    def test_phase3_has_two_agents(self):
        self.assertEqual(len(self.defn["phases"][2]["agents"]), 2)

    # ------------------------------------------------------------------
    # All agents have required fields
    # ------------------------------------------------------------------

    def test_all_agents_have_label(self):
        for phase in self.defn["phases"]:
            for agent in phase["agents"]:
                self.assertIn("label", agent, f"Agent missing label: {agent}")

    def test_all_agents_have_prompt(self):
        for phase in self.defn["phases"]:
            for agent in phase["agents"]:
                self.assertIn("prompt", agent, f"Agent missing prompt: {agent.get('label')}")
                self.assertTrue(agent["prompt"].strip(), f"Empty prompt: {agent.get('label')}")

    def test_all_agents_have_effort(self):
        for phase in self.defn["phases"]:
            for agent in phase["agents"]:
                self.assertIn("effort", agent, f"Agent missing effort: {agent.get('label')}")

    # ------------------------------------------------------------------
    # Speedup model — ≥20% reduction claim
    # ------------------------------------------------------------------

    def test_speedup_model_present(self):
        self.assertIn("speedup_model", self.defn)

    def test_speedup_model_ratio_at_most_0_80(self):
        ratio = self.defn["speedup_model"]["estimated_wall_clock_ratio"]
        self.assertLessEqual(ratio, 0.80, "speedup_model must claim ≥20% reduction (ratio ≤ 0.80)")

    def test_speedup_model_ratio_positive(self):
        ratio = self.defn["speedup_model"]["estimated_wall_clock_ratio"]
        self.assertGreater(ratio, 0.0)

    def test_speedup_model_has_rationale(self):
        self.assertIn("rationale", self.defn["speedup_model"])
        self.assertTrue(self.defn["speedup_model"]["rationale"].strip())

    def test_speedup_model_phase_parallelism(self):
        parallelism = self.defn["speedup_model"]["phase_parallelism"]
        self.assertIsInstance(parallelism, list)
        self.assertEqual(len(parallelism), 3)
        for p in parallelism:
            self.assertGreaterEqual(p, 2, "Each phase must have ≥2 concurrent agents")


class TestFeatureImplementationRegistry(unittest.TestCase):
    """Integration checks via WorkflowRegistry."""

    def setUp(self):
        from src.workflow_registry import WorkflowRegistry
        self.registry = WorkflowRegistry()

    def test_workflow_registered(self):
        self.assertIn("feature_implementation", self.registry.listWorkflows())

    def test_get_workflow_returns_defn(self):
        defn = self.registry.getWorkflow("feature_implementation")
        self.assertEqual(defn["name"], "feature_implementation")

    def test_execute_workflow_ok(self):
        result = self.registry.executeWorkflow("feature_implementation", context="test context")
        self.assertTrue(result["ok"])
        self.assertEqual(result["name"], "feature_implementation")

    def test_execute_workflow_prompt_contains_phases(self):
        result = self.registry.executeWorkflow("feature_implementation")
        prompt = result["prompt"]
        self.assertIn("Design", prompt)
        self.assertIn("Implement and verify", prompt)
        self.assertIn("Test and document", prompt)

    def test_execute_workflow_prompt_has_agent_labels(self):
        result = self.registry.executeWorkflow("feature_implementation")
        prompt = result["prompt"]
        for label in ("design", "test-design", "implement", "security-review", "test", "doc-update"):
            self.assertIn(label, prompt, f"Label '{label}' missing from executed prompt")

    def test_execute_workflow_contains_context(self):
        ctx = "sample-feature-ctx-001"
        result = self.registry.executeWorkflow("feature_implementation", context=ctx)
        self.assertIn(ctx, result["prompt"])

    def test_parallel_phases_marked_in_prompt(self):
        result = self.registry.executeWorkflow("feature_implementation")
        prompt = result["prompt"]
        self.assertEqual(prompt.count("(parallel)"), 3)
