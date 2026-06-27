"""Tests for workflows/registry.py — load, validate, and edge-case behaviour.

Covers:
  - All three shipped definition files load cleanly (success-rate gate).
  - Loaded definitions satisfy required structural shape (phases, agents, effort).
  - Validation rejects unknown keys, bad types, and invalid effort values.
  - Registry skips invalid/unreadable files and keeps the rest (partial failure).
  - Duplicate workflow names: first definition wins, second is silently dropped.
  - Empty and missing definitions directories return an empty registry.
  - Module-level REGISTRY is populated on import.
"""
from __future__ import annotations

import json
import logging
import unittest
from pathlib import Path

from workflows.registry import _validateAgent, _validatePhase, _validateWorkflowDefinition, loadRegistry
from workflows import registry as _reg_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(directory: Path, filename: str, data: object) -> Path:
    p = directory / filename
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Unit: _validateAgent
# ---------------------------------------------------------------------------

class TestValidateAgent(unittest.TestCase):
    def test_valid_full_agent_returns_none(self):
        agent = {"label": "correctness", "prompt": "Find bugs.", "effort": "high"}
        self.assertIsNone(_validateAgent(agent, "path"))

    def test_valid_minimal_agent_returns_none(self):
        self.assertIsNone(_validateAgent({}, "path"))

    def test_non_dict_returns_error(self):
        self.assertIsNotNone(_validateAgent("bad", "path"))

    def test_unknown_key_returns_error(self):
        err = _validateAgent({"label": "x", "unknown": True}, "path")
        self.assertIsNotNone(err)
        self.assertIn("unknown", err)

    def test_effort_must_be_string(self):
        err = _validateAgent({"effort": 99}, "path")
        self.assertIsNotNone(err)

    def test_invalid_effort_value_returns_error(self):
        err = _validateAgent({"effort": "turbo"}, "path")
        self.assertIsNotNone(err)
        self.assertIn("turbo", err)

    def test_all_valid_effort_values_accepted(self):
        for effort in ("default", "high", "xhigh", "ultracode"):
            with self.subTest(effort=effort):
                self.assertIsNone(_validateAgent({"effort": effort}, "path"))

    def test_prompt_must_be_string(self):
        err = _validateAgent({"prompt": 42}, "path")
        self.assertIsNotNone(err)

    def test_label_must_be_string(self):
        err = _validateAgent({"label": []}, "path")
        self.assertIsNotNone(err)


# ---------------------------------------------------------------------------
# Unit: _validatePhase
# ---------------------------------------------------------------------------

class TestValidatePhase(unittest.TestCase):
    def test_valid_phase_returns_none(self):
        phase = {
            "title": "Scan",
            "parallel": True,
            "agents": [{"label": "x", "prompt": "p", "effort": "default"}],
        }
        self.assertIsNone(_validatePhase(phase, "path"))

    def test_non_dict_returns_error(self):
        self.assertIsNotNone(_validatePhase([], "path"))

    def test_unknown_key_returns_error(self):
        err = _validatePhase({"title": "T", "extra": 1}, "path")
        self.assertIsNotNone(err)

    def test_title_must_be_string(self):
        err = _validatePhase({"title": 123}, "path")
        self.assertIsNotNone(err)

    def test_parallel_must_be_bool(self):
        err = _validatePhase({"parallel": "yes"}, "path")
        self.assertIsNotNone(err)

    def test_agents_must_be_list(self):
        err = _validatePhase({"agents": "bad"}, "path")
        self.assertIsNotNone(err)

    def test_invalid_agent_inside_phase_propagates_error(self):
        err = _validatePhase({"agents": [{"effort": "bad"}]}, "path")
        self.assertIsNotNone(err)

    def test_empty_agents_list_is_valid(self):
        self.assertIsNone(_validatePhase({"agents": []}, "path"))


# ---------------------------------------------------------------------------
# Unit: _validateWorkflowDefinition
# ---------------------------------------------------------------------------

class TestValidateWorkflowDefinition(unittest.TestCase):
    def _make_valid(self) -> dict:
        return {
            "name": "test-wf",
            "description": "desc",
            "phases": [
                {"title": "Phase 1", "parallel": False, "agents": [
                    {"label": "a", "prompt": "do x", "effort": "default"},
                ]},
            ],
            "synthesis": "combine",
        }

    def test_full_valid_definition_returns_none(self):
        self.assertIsNone(_validateWorkflowDefinition(self._make_valid(), "src"))

    def test_non_dict_root_returns_error(self):
        self.assertIsNotNone(_validateWorkflowDefinition([], "src"))

    def test_unknown_root_key_returns_error(self):
        d = self._make_valid()
        d["extra"] = True
        err = _validateWorkflowDefinition(d, "src")
        self.assertIsNotNone(err)

    def test_name_must_be_string(self):
        d = self._make_valid()
        d["name"] = 1
        self.assertIsNotNone(_validateWorkflowDefinition(d, "src"))

    def test_description_must_be_string(self):
        d = self._make_valid()
        d["description"] = {}
        self.assertIsNotNone(_validateWorkflowDefinition(d, "src"))

    def test_synthesis_must_be_string(self):
        d = self._make_valid()
        d["synthesis"] = 99
        self.assertIsNotNone(_validateWorkflowDefinition(d, "src"))

    def test_phases_must_be_list(self):
        d = self._make_valid()
        d["phases"] = "bad"
        self.assertIsNotNone(_validateWorkflowDefinition(d, "src"))

    def test_invalid_phase_inside_definition_propagates_error(self):
        d = self._make_valid()
        d["phases"] = [{"unknown_key": True}]
        self.assertIsNotNone(_validateWorkflowDefinition(d, "src"))

    def test_empty_definition_is_valid(self):
        self.assertIsNone(_validateWorkflowDefinition({}, "src"))


# ---------------------------------------------------------------------------
# Integration: loadRegistry with a tmp directory
# ---------------------------------------------------------------------------

class TestLoadRegistry(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.defs_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _valid_wf(self, name: str) -> dict:
        return {
            "name": name,
            "description": f"desc of {name}",
            "phases": [{"title": "P", "parallel": False, "agents": []}],
            "synthesis": "done",
        }

    # Happy path ----------------------------------------------------------

    def test_single_valid_file_is_loaded(self):
        _write_json(self.defs_dir, "alpha.json", self._valid_wf("alpha"))
        reg = loadRegistry(self.defs_dir)
        self.assertIn("alpha", reg)
        self.assertEqual(reg["alpha"]["name"], "alpha")

    def test_multiple_valid_files_all_loaded(self):
        for name in ("a", "b", "c"):
            _write_json(self.defs_dir, f"{name}.json", self._valid_wf(name))
        reg = loadRegistry(self.defs_dir)
        self.assertEqual(set(reg.keys()), {"a", "b", "c"})

    def test_name_falls_back_to_file_stem_when_name_absent(self):
        data = {"description": "no name field", "phases": []}
        _write_json(self.defs_dir, "fallback.json", data)
        reg = loadRegistry(self.defs_dir)
        self.assertIn("fallback", reg)

    # Partial failure tolerance -------------------------------------------

    def test_invalid_json_file_is_skipped(self):
        bad = self.defs_dir / "bad.json"
        bad.write_text("NOT JSON {{{{", encoding="utf-8")
        _write_json(self.defs_dir, "good.json", self._valid_wf("good"))
        reg = loadRegistry(self.defs_dir)
        self.assertIn("good", reg)
        self.assertNotIn("bad", reg)

    def test_invalid_definition_is_skipped(self):
        _write_json(self.defs_dir, "broken.json", {"unknown_key": True})
        _write_json(self.defs_dir, "ok.json", self._valid_wf("ok"))
        reg = loadRegistry(self.defs_dir)
        self.assertIn("ok", reg)
        self.assertNotIn("broken", reg)

    def test_invalid_effort_definition_is_skipped(self):
        bad = {
            "name": "bad-effort",
            "phases": [{"title": "P", "agents": [{"effort": "INVALID"}]}],
        }
        _write_json(self.defs_dir, "bad_effort.json", bad)
        reg = loadRegistry(self.defs_dir)
        self.assertNotIn("bad-effort", reg)

    # Duplicate handling --------------------------------------------------

    def test_duplicate_name_first_definition_kept(self):
        # Two files with the same `name` field: alphabetically first file wins.
        first = self._valid_wf("dup")
        first["description"] = "first"
        second = self._valid_wf("dup")
        second["description"] = "second"
        _write_json(self.defs_dir, "a_dup.json", first)
        _write_json(self.defs_dir, "b_dup.json", second)
        reg = loadRegistry(self.defs_dir)
        self.assertEqual(reg["dup"]["description"], "first")

    # Edge cases ----------------------------------------------------------

    def test_empty_directory_returns_empty_registry(self):
        reg = loadRegistry(self.defs_dir)
        self.assertEqual(reg, {})

    def test_missing_directory_returns_empty_registry(self):
        missing = Path(self._tmp.name) / "does_not_exist"
        reg = loadRegistry(missing)
        self.assertEqual(reg, {})

    def test_non_json_files_ignored(self):
        (self.defs_dir / "readme.txt").write_text("not json", encoding="utf-8")
        reg = loadRegistry(self.defs_dir)
        self.assertEqual(reg, {})

    def test_registry_returns_dict(self):
        reg = loadRegistry(self.defs_dir)
        self.assertIsInstance(reg, dict)

    def test_warning_logged_for_invalid_definition(self):
        _write_json(self.defs_dir, "bad.json", {"unknown_key": True})
        with self.assertLogs("workflows.registry", level=logging.WARNING):
            loadRegistry(self.defs_dir)


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
