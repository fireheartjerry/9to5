"""tests/test_bug_investigation.py -- Validate the enhanced bug_investigation workflow.

Verifies:
  - Workflow JSON is valid and loads via WorkflowRegistry.
  - Phase 1 is now parallel (reproduce + static-analysis concurrent).
  - Phase 2 remains parallel (trace-data-flow + trace-control-flow).
  - Phase 3 is now parallel (patch + test-scaffold concurrent).
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

_DEFN_PATH = _ROOT / "workflows" / "definitions" / "bug_investigation.json"


def _load_defn() -> dict:
    with _DEFN_PATH.open() as f:
        return json.load(f)


class TestBugInvestigationJson(unittest.TestCase):
    """Structural checks on the raw JSON definition."""

    def setUp(self):
        self.defn = _load_defn()

    def test_file_exists(self):
        self.assertTrue(_DEFN_PATH.exists(), f"Missing: {_DEFN_PATH}")

    def test_name_field(self):
        self.assertEqual(self.defn["name"], "bug_investigation")

    def test_has_three_phases(self):
        self.assertEqual(len(self.defn["phases"]), 3)

    def test_has_synthesis(self):
        self.assertIn("synthesis", self.defn)
        self.assertIsInstance(self.defn["synthesis"], str)
        self.assertTrue(self.defn["synthesis"].strip())

    # ------------------------------------------------------------------
    # Phase 1: Reproduce and static-analysis — now PARALLEL
    # ------------------------------------------------------------------

    def test_phase1_is_parallel(self):
        phase = self.defn["phases"][0]
        self.assertTrue(phase.get("parallel"), "Phase 1 must be parallel for concurrent speedup")

    def test_phase1_has_reproduce_agent(self):
        labels = {a["label"] for a in self.defn["phases"][0]["agents"]}
        self.assertIn("reproduce", labels)

    def test_phase1_has_static_analysis_agent(self):
        labels = {a["label"] for a in self.defn["phases"][0]["agents"]}
        self.assertIn("static-analysis", labels)

    def test_phase1_has_two_agents(self):
        self.assertEqual(len(self.defn["phases"][0]["agents"]), 2)

    # ------------------------------------------------------------------
    # Phase 2: Parallel hypothesis — unchanged
    # ------------------------------------------------------------------

    def test_phase2_is_parallel(self):
        phase = self.defn["phases"][1]
        self.assertTrue(phase.get("parallel"), "Phase 2 must remain parallel")

    def test_phase2_has_trace_data_flow(self):
        labels = {a["label"] for a in self.defn["phases"][1]["agents"]}
        self.assertIn("trace-data-flow", labels)

    def test_phase2_has_trace_control_flow(self):
        labels = {a["label"] for a in self.defn["phases"][1]["agents"]}
        self.assertIn("trace-control-flow", labels)

    # ------------------------------------------------------------------
    # Phase 3: Fix and test-scaffold — now PARALLEL
    # ------------------------------------------------------------------

    def test_phase3_is_parallel(self):
        phase = self.defn["phases"][2]
        self.assertTrue(phase.get("parallel"), "Phase 3 must be parallel for concurrent speedup")

    def test_phase3_has_patch_agent(self):
        labels = {a["label"] for a in self.defn["phases"][2]["agents"]}
        self.assertIn("patch", labels)

    def test_phase3_has_test_scaffold_agent(self):
        labels = {a["label"] for a in self.defn["phases"][2]["agents"]}
        self.assertIn("test-scaffold", labels)

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
        # All phases should have ≥2 concurrent agents
        for p in parallelism:
            self.assertGreaterEqual(p, 2, "Each phase must have ≥2 concurrent agents")


class TestBugInvestigationRegistry(unittest.TestCase):
    """Integration checks via WorkflowRegistry."""

    def setUp(self):
        from src.workflow_registry import WorkflowRegistry
        self.registry = WorkflowRegistry()

    def test_workflow_registered(self):
        self.assertIn("bug_investigation", self.registry.listWorkflows())

    def test_get_workflow_returns_defn(self):
        defn = self.registry.getWorkflow("bug_investigation")
        self.assertEqual(defn["name"], "bug_investigation")

    def test_execute_workflow_ok(self):
        result = self.registry.executeWorkflow("bug_investigation", context="test context")
        self.assertTrue(result["ok"])
        self.assertEqual(result["name"], "bug_investigation")

    def test_execute_workflow_prompt_contains_phases(self):
        result = self.registry.executeWorkflow("bug_investigation")
        prompt = result["prompt"]
        self.assertIn("Reproduce and static-analysis", prompt)
        self.assertIn("Parallel hypothesis", prompt)
        self.assertIn("Fix and test-scaffold", prompt)

    def test_execute_workflow_prompt_has_agent_labels(self):
        result = self.registry.executeWorkflow("bug_investigation")
        prompt = result["prompt"]
        for label in ("reproduce", "static-analysis", "trace-data-flow",
                      "trace-control-flow", "patch", "test-scaffold"):
            self.assertIn(label, prompt, f"Label '{label}' missing from executed prompt")

    def test_execute_workflow_contains_context(self):
        ctx = "sample-bug-ctx-001"
        result = self.registry.executeWorkflow("bug_investigation", context=ctx)
        self.assertIn(ctx, result["prompt"])

    def test_parallel_phases_marked_in_prompt(self):
        result = self.registry.executeWorkflow("bug_investigation")
        prompt = result["prompt"]
        # All 3 phases are parallel
        self.assertEqual(prompt.count("(parallel)"), 3)
