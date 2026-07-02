"""Tests for workflows/registry.py — shipped definitions and module-level registry.

Covers:
  - Acceptance-criteria gate: all three shipped workflow definitions load cleanly.
  - Module-level REGISTRY is populated on import.

Split from test_workflows_registry.py (was 389 lines).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from workflows.registry import loadRegistry
from workflows import registry as _reg_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(directory: Path, filename: str, data: object) -> Path:
    p = directory / filename
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Acceptance-criteria gate: shipped definitions must all load cleanly
# ---------------------------------------------------------------------------

class TestShippedDefinitions(unittest.TestCase):
    """Verify the three bundled workflow definitions load without errors.

    This is the primary success-rate gate from the acceptance criteria:
    all shipped workflows must be valid and present in the registry.
    """

    EXPECTED_WORKFLOWS = {"code_review", "bug_investigation", "feature_implementation"}

    def test_all_shipped_workflows_load(self):
        from workflows.registry import DEFINITIONS_DIR
        reg = loadRegistry(DEFINITIONS_DIR)
        missing = self.EXPECTED_WORKFLOWS - set(reg.keys())
        self.assertFalse(
            missing,
            f"Shipped workflow definitions failed to load: {missing}",
        )

    def test_success_rate_is_100_percent(self):
        """All known definitions load; zero are skipped due to validation errors."""
        from workflows.registry import DEFINITIONS_DIR
        reg = loadRegistry(DEFINITIONS_DIR)
        loaded_count = len([k for k in reg if k in self.EXPECTED_WORKFLOWS])
        rate = loaded_count / len(self.EXPECTED_WORKFLOWS)
        self.assertGreaterEqual(
            rate, 0.9,
            f"Workflow load success rate {rate:.0%} below 90% threshold",
        )

    def test_code_review_has_parallel_phase(self):
        from workflows.registry import DEFINITIONS_DIR
        reg = loadRegistry(DEFINITIONS_DIR)
        wf = reg["code_review"]
        parallel_phases = [p for p in wf.get("phases", []) if p.get("parallel")]
        self.assertTrue(parallel_phases, "code_review must have at least one parallel phase")

    def test_code_review_has_three_agents(self):
        from workflows.registry import DEFINITIONS_DIR
        reg = loadRegistry(DEFINITIONS_DIR)
        wf = reg["code_review"]
        all_agents = [a for p in wf.get("phases", []) for a in p.get("agents", [])]
        self.assertEqual(len(all_agents), 3)

    def test_bug_investigation_has_three_phases(self):
        from workflows.registry import DEFINITIONS_DIR
        reg = loadRegistry(DEFINITIONS_DIR)
        wf = reg["bug_investigation"]
        self.assertEqual(len(wf.get("phases", [])), 3)

    def test_feature_implementation_has_three_phases(self):
        from workflows.registry import DEFINITIONS_DIR
        reg = loadRegistry(DEFINITIONS_DIR)
        wf = reg["feature_implementation"]
        self.assertEqual(len(wf.get("phases", [])), 3)

    def test_all_agents_have_valid_effort(self):
        from workflows.registry import DEFINITIONS_DIR, _VALID_EFFORT_VALUES
        reg = loadRegistry(DEFINITIONS_DIR)
        for wf_name, wf in reg.items():
            for phase in wf.get("phases", []):
                for agent in phase.get("agents", []):
                    if "effort" in agent:
                        self.assertIn(
                            agent["effort"], _VALID_EFFORT_VALUES,
                            f"{wf_name}: agent '{agent.get('label')}' has invalid effort '{agent['effort']}'",
                        )

    def test_all_definitions_have_synthesis(self):
        from workflows.registry import DEFINITIONS_DIR
        reg = loadRegistry(DEFINITIONS_DIR)
        for wf_name in self.EXPECTED_WORKFLOWS:
            with self.subTest(workflow=wf_name):
                self.assertIn(
                    "synthesis", reg[wf_name],
                    f"{wf_name} is missing a 'synthesis' key",
                )
                self.assertTrue(reg[wf_name]["synthesis"].strip())

    def test_all_definitions_have_description(self):
        from workflows.registry import DEFINITIONS_DIR
        reg = loadRegistry(DEFINITIONS_DIR)
        for wf_name in self.EXPECTED_WORKFLOWS:
            with self.subTest(workflow=wf_name):
                self.assertIn("description", reg[wf_name])
                self.assertTrue(reg[wf_name]["description"].strip())


# ---------------------------------------------------------------------------
# Module-level REGISTRY is populated on import
# ---------------------------------------------------------------------------

class TestModuleLevelRegistry(unittest.TestCase):
    def test_registry_constant_is_dict(self):
        self.assertIsInstance(_reg_module.REGISTRY, dict)

    def test_registry_is_non_empty(self):
        self.assertGreater(len(_reg_module.REGISTRY), 0)

    def test_registry_contains_shipped_workflows(self):
        for name in ("code_review", "bug_investigation", "feature_implementation"):
            with self.subTest(name=name):
                self.assertIn(name, _reg_module.REGISTRY)


if __name__ == "__main__":
    unittest.main()
