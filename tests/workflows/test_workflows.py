"""test_workflows.py -- Acceptance test: all workflows optimized for >=20% time reduction.

Verifies that every shipped workflow definition uses parallelism to achieve
at least a 20% reduction in wall-clock execution time vs a fully sequential
baseline, and that all quality gates (synthesis, descriptions, effort values)
are satisfied.

RUN: python tests/test_workflows.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from workflows.registry import DEFINITIONS_DIR, _VALID_EFFORT_VALUES, loadRegistry  # noqa: E402

_MIN_REDUCTION = 0.20  # 20% wall-clock time reduction threshold


def _computeTimeReduction(wf: dict) -> float:
    """Fraction of wall-clock time saved by parallelism vs fully sequential execution.

    Model: each agent takes 1 time unit. A parallel phase runs all its agents in
    1 unit; a sequential phase runs each agent serially. Returns 0.0 when there
    are no phases.
    """
    sequential_total = 0
    parallel_total = 0
    for phase in wf.get("phases", []):
        agent_count = max(len(phase.get("agents", [])), 1)
        sequential_total += agent_count
        if phase.get("parallel", False):
            parallel_total += 1  # all agents run concurrently
        else:
            parallel_total += agent_count
    if sequential_total == 0:
        return 0.0
    return (sequential_total - parallel_total) / sequential_total


class TestWorkflowPresence(unittest.TestCase):
    """All shipped workflow definitions must load from the registry."""

    EXPECTED = {"code_review", "bug_investigation", "feature_implementation"}

    def setUp(self):
        self.registry = loadRegistry(DEFINITIONS_DIR)

    def test_all_expected_workflows_present(self):
        missing = self.EXPECTED - set(self.registry.keys())
        self.assertFalse(missing, f"Workflows missing from registry: {missing}")

    def test_all_workflows_have_phases(self):
        for name in self.EXPECTED:
            with self.subTest(workflow=name):
                phases = self.registry[name].get("phases", [])
                self.assertGreater(len(phases), 0, f"{name}: must have at least one phase")

    def test_all_workflows_have_synthesis(self):
        for name in self.EXPECTED:
            with self.subTest(workflow=name):
                wf = self.registry[name]
                self.assertIn("synthesis", wf, f"{name}: missing synthesis key")
                self.assertTrue(wf["synthesis"].strip(), f"{name}: synthesis must not be blank")

    def test_all_workflows_have_description(self):
        for name in self.EXPECTED:
            with self.subTest(workflow=name):
                wf = self.registry[name]
                self.assertIn("description", wf, f"{name}: missing description key")
                self.assertTrue(wf["description"].strip(), f"{name}: description must not be blank")

    def test_all_agents_have_valid_effort(self):
        for wf_name in self.EXPECTED:
            wf = self.registry[wf_name]
            for phase in wf.get("phases", []):
                for agent in phase.get("agents", []):
                    if "effort" in agent:
                        with self.subTest(workflow=wf_name, agent=agent.get("label")):
                            self.assertIn(
                                agent["effort"], _VALID_EFFORT_VALUES,
                                f"{wf_name}/{agent.get('label')}: invalid effort '{agent['effort']}'",
                            )


class TestWorkflowOptimization(unittest.TestCase):
    """Each shipped workflow must achieve >=20% wall-clock time reduction via parallelism."""

    def setUp(self):
        self.registry = loadRegistry(DEFINITIONS_DIR)

    def _assertReduction(self, wf_name: str) -> None:
        wf = self.registry[wf_name]
        reduction = _computeTimeReduction(wf)
        self.assertGreaterEqual(
            reduction,
            _MIN_REDUCTION,
            f"{wf_name}: parallelism saves only {reduction:.1%} wall-clock time "
            f"(threshold: {_MIN_REDUCTION:.0%}). Add a parallel phase.",
        )

    def test_code_review_reduction(self):
        self._assertReduction("code_review")

    def test_bug_investigation_reduction(self):
        self._assertReduction("bug_investigation")

    def test_feature_implementation_reduction(self):
        self._assertReduction("feature_implementation")

    def test_aggregate_reduction_across_all_workflows(self):
        """System-level: mean parallelism savings across all shipped workflows >= 20%."""
        names = ("code_review", "bug_investigation", "feature_implementation")
        reductions = [_computeTimeReduction(self.registry[n]) for n in names]
        avg = sum(reductions) / len(reductions)
        self.assertGreaterEqual(
            avg,
            _MIN_REDUCTION,
            f"Mean time reduction {avg:.1%} < {_MIN_REDUCTION:.0%} threshold. "
            f"Per-workflow: {dict(zip(names, [f'{r:.1%}' for r in reductions]))}",
        )


class TestParallelPhaseStructure(unittest.TestCase):
    """Structural checks: workflows that can parallelize, do."""

    def setUp(self):
        self.registry = loadRegistry(DEFINITIONS_DIR)

    def test_code_review_has_parallel_phase(self):
        wf = self.registry["code_review"]
        parallel = [p for p in wf.get("phases", []) if p.get("parallel")]
        self.assertTrue(parallel, "code_review must have at least one parallel phase")

    def test_bug_investigation_has_parallel_phase(self):
        wf = self.registry["bug_investigation"]
        parallel = [p for p in wf.get("phases", []) if p.get("parallel")]
        self.assertTrue(parallel, "bug_investigation must have at least one parallel phase")

    def test_feature_implementation_has_parallel_phase(self):
        wf = self.registry["feature_implementation"]
        parallel = [p for p in wf.get("phases", []) if p.get("parallel")]
        self.assertTrue(parallel, "feature_implementation must have at least one parallel phase")

    def test_code_review_parallel_phase_has_multiple_agents(self):
        wf = self.registry["code_review"]
        for phase in wf.get("phases", []):
            if phase.get("parallel"):
                self.assertGreater(
                    len(phase.get("agents", [])), 1,
                    "code_review parallel phase must have >1 agent to be meaningful",
                )
