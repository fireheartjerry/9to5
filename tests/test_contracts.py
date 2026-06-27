"""The frozen domain dataclasses mirror their real producers (contracts.py)."""
import unittest

import platform_core.core.contracts as contracts
from platform_core.core.contracts import (AgentDecision, ControlCommand, SubtaskSpec, Universe,
                       VerificationResult, WorkflowAgent, WorkflowDefinition, WorkflowPhase)

try:
    from tests.factories import make_subtask
except Exception:  # pragma: no cover - factories import shape varies by runner
    from factories import make_subtask


class TestSubtaskSpec(unittest.TestCase):
    def test_fromdict_wraps_a_real_factory_subtask(self):
        # Grounded against the canonical builder so field drift is caught here.
        d = make_subtask(title="do x")
        spec = SubtaskSpec.fromDict(d)
        self.assertEqual(spec.subtask_id, d["subtask_id"])
        self.assertEqual(spec.title, "do x")
        self.assertIsInstance(spec.depends_on, tuple)

    def test_is_frozen(self):
        spec = SubtaskSpec(subtask_id="st-001")
        with self.assertRaises(Exception):
            spec.title = "mutated"  # frozen


class TestVerificationResult(unittest.TestCase):
    def test_fromdict_matches_verifier_output_shape(self):
        # Exact mirror of agents/verifier.runVerification() return.
        raw = {"passed": True, "cmd": "pytest -q", "expect": "exit_zero",
               "returncode": 0, "stdout": "1 passed", "stderr": ""}
        r = VerificationResult.fromDict(raw)
        self.assertTrue(r.passed)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.cmd, "pytest -q")


class TestUniverse(unittest.TestCase):
    def test_fromdict_none_is_empty_not_crash(self):
        u = Universe.fromDict(None)
        self.assertEqual(u.hard_boundaries, ())

    def test_fromdict_preserves_boundaries(self):
        u = Universe.fromDict({"hard_boundaries": [".env", ".git"]})
        self.assertIn(".env", u.hard_boundaries)


class TestSmallValues(unittest.TestCase):
    def test_control_command(self):
        c = ControlCommand(name="skip", arg="st-001")
        self.assertEqual((c.name, c.arg), ("skip", "st-001"))

    def test_agent_decision_defaults_are_safe(self):
        d = AgentDecision()
        self.assertEqual(d.risk, "low")
        self.assertFalse(d.needs_human_review)

    def test_module_exports_the_spine(self):
        for name in ("Goal", "ElaboratedGoal", "Universe", "SubtaskSpec",
                     "VerificationResult", "ControlCommand", "AgentDecision",
                     "WorkflowAgent", "WorkflowPhase", "WorkflowDefinition"):
            self.assertTrue(hasattr(contracts, name), name)


class TestWorkflowDefinition(unittest.TestCase):
    def test_minimal_definition_is_valid_typed_dict(self):
        wf: WorkflowDefinition = {
            "name": "audit-pipeline",
            "description": "Three-phase audit workflow",
            "phases": [],
            "synthesis": "Merge phase outputs into a final report.",
        }
        self.assertEqual(wf["name"], "audit-pipeline")
        self.assertEqual(wf["synthesis"], "Merge phase outputs into a final report.")

    def test_phase_with_parallel_agents(self):
        agent: WorkflowAgent = {"label": "find-bugs", "prompt": "Find all bugs.", "effort": "high"}
        phase: WorkflowPhase = {"title": "Scan", "parallel": True, "agents": [agent]}
        self.assertTrue(phase["parallel"])
        self.assertEqual(phase["agents"][0]["label"], "find-bugs")

    def test_definition_nested_in_invocation_spec(self):
        from platform_core.core.contracts import InvocationSpec
        spec: InvocationSpec = {
            "use_workflow": True,
            "workflow_definition": {
                "name": "wf",
                "description": "desc",
                "phases": [{"title": "P1", "parallel": False, "agents": []}],
                "synthesis": "combine",
            },
        }
        self.assertEqual(spec["workflow_definition"]["name"], "wf")

    def test_total_false_allows_partial_construction(self):
        # total=False means no key is required at runtime (TypedDict erased).
        wf: WorkflowDefinition = {"name": "minimal"}
        self.assertNotIn("phases", wf)


if __name__ == "__main__":
    unittest.main()
