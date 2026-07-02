"""Tests for src/workflow_registry.py -- centralized mutable workflow registry.

Acceptance check for subtask st-055: Create Centralized Workflow Registry.
Exit 0 expected on all tests passing.
"""
from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.workflow_registry import (  # noqa: E402
    REGISTRY,
    WorkflowNotFoundError,
    WorkflowRegistry,
    WorkflowValidationError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_reg() -> WorkflowRegistry:
    """Return a WorkflowRegistry with no definitions loaded."""
    reg = WorkflowRegistry.__new__(WorkflowRegistry)
    reg._lock = threading.Lock()
    reg._store = {}
    return reg


def _valid_wf(name: str = "test") -> dict:
    return {
        "name": name,
        "description": f"description of {name}",
        "phases": [
            {
                "title": "Phase 1",
                "parallel": False,
                "agents": [{"label": "a", "prompt": "do x", "effort": "default"}],
            }
        ],
        "synthesis": "combine",
    }


# ---------------------------------------------------------------------------
# addWorkflow
# ---------------------------------------------------------------------------

class TestAddWorkflow(unittest.TestCase):
    def setUp(self):
        self.reg = _empty_reg()

    def test_add_valid_workflow_is_retrievable(self):
        self.reg.addWorkflow("alpha", _valid_wf("alpha"))
        self.assertIn("alpha", self.reg.listWorkflows())

    def test_add_overwrites_existing(self):
        self.reg.addWorkflow("x", _valid_wf("x"))
        wf2 = _valid_wf("x")
        wf2["description"] = "updated"
        self.reg.addWorkflow("x", wf2)
        self.assertEqual(self.reg.getWorkflow("x")["description"], "updated")

    def test_add_invalid_raises_validation_error(self):
        with self.assertRaises(WorkflowValidationError):
            self.reg.addWorkflow("bad", {"unknown_key": True})

    def test_add_bad_effort_raises_validation_error(self):
        bad = _valid_wf("bad")
        bad["phases"][0]["agents"][0]["effort"] = "INVALID"
        with self.assertRaises(WorkflowValidationError):
            self.reg.addWorkflow("bad", bad)

    def test_add_minimal_workflow_ok(self):
        self.reg.addWorkflow("minimal", {})
        self.assertIn("minimal", self.reg.listWorkflows())

    def test_add_multiple_distinct_names(self):
        for name in ("a", "b", "c"):
            self.reg.addWorkflow(name, _valid_wf(name))
        self.assertEqual(set(self.reg.listWorkflows()), {"a", "b", "c"})


# ---------------------------------------------------------------------------
# removeWorkflow
# ---------------------------------------------------------------------------

class TestRemoveWorkflow(unittest.TestCase):
    def setUp(self):
        self.reg = _empty_reg()
        self.reg.addWorkflow("z", _valid_wf("z"))

    def test_remove_returns_definition(self):
        removed = self.reg.removeWorkflow("z")
        self.assertEqual(removed["name"], "z")

    def test_remove_is_no_longer_listed(self):
        self.reg.removeWorkflow("z")
        self.assertNotIn("z", self.reg.listWorkflows())

    def test_remove_nonexistent_raises(self):
        with self.assertRaises(WorkflowNotFoundError):
            self.reg.removeWorkflow("no-such-workflow")

    def test_remove_twice_raises_second_time(self):
        self.reg.removeWorkflow("z")
        with self.assertRaises(WorkflowNotFoundError):
            self.reg.removeWorkflow("z")


# ---------------------------------------------------------------------------
# getWorkflow
# ---------------------------------------------------------------------------

class TestGetWorkflow(unittest.TestCase):
    def setUp(self):
        self.reg = _empty_reg()
        self.reg.addWorkflow("g", _valid_wf("g"))

    def test_get_existing_returns_definition(self):
        defn = self.reg.getWorkflow("g")
        self.assertEqual(defn["name"], "g")

    def test_get_missing_raises(self):
        with self.assertRaises(WorkflowNotFoundError):
            self.reg.getWorkflow("missing")

    def test_get_returns_full_definition(self):
        defn = self.reg.getWorkflow("g")
        self.assertIn("phases", defn)
        self.assertIn("synthesis", defn)


# ---------------------------------------------------------------------------
# listWorkflows
# ---------------------------------------------------------------------------

class TestListWorkflows(unittest.TestCase):
    def test_empty_registry_returns_empty_list(self):
        reg = _empty_reg()
        self.assertEqual(reg.listWorkflows(), [])

    def test_list_returns_all_names(self):
        reg = _empty_reg()
        reg.addWorkflow("a", _valid_wf("a"))
        reg.addWorkflow("b", _valid_wf("b"))
        self.assertCountEqual(reg.listWorkflows(), ["a", "b"])

    def test_list_is_a_snapshot(self):
        reg = _empty_reg()
        reg.addWorkflow("snap", _valid_wf("snap"))
        names = reg.listWorkflows()
        reg.addWorkflow("extra", _valid_wf("extra"))
        self.assertNotIn("extra", names)


# ---------------------------------------------------------------------------
# executeWorkflow
# ---------------------------------------------------------------------------

class TestExecuteWorkflow(unittest.TestCase):
    def setUp(self):
        self.reg = _empty_reg()
        self.reg.addWorkflow("wf", {
            "name": "wf",
            "description": "test workflow",
            "phases": [
                {
                    "title": "Phase 1",
                    "parallel": False,
                    "agents": [{"label": "a", "prompt": "do x", "effort": "default"}],
                }
            ],
            "synthesis": "combine results",
        })

    def test_execute_returns_dict(self):
        result = self.reg.executeWorkflow("wf")
        self.assertIsInstance(result, dict)

    def test_execute_ok_true(self):
        result = self.reg.executeWorkflow("wf")
        self.assertTrue(result["ok"])

    def test_execute_includes_name(self):
        result = self.reg.executeWorkflow("wf")
        self.assertEqual(result["name"], "wf")

    def test_execute_includes_prompt(self):
        result = self.reg.executeWorkflow("wf")
        self.assertIn("prompt", result)
        self.assertIn("do x", result["prompt"])

    def test_execute_includes_workflow_definition(self):
        result = self.reg.executeWorkflow("wf")
        self.assertIn("workflow", result)
        self.assertEqual(result["workflow"]["name"], "wf")

    def test_execute_with_context_appears_in_prompt(self):
        result = self.reg.executeWorkflow("wf", context="fix bug #42")
        self.assertIn("fix bug #42", result["prompt"])

    def test_execute_synthesis_appears_in_prompt(self):
        result = self.reg.executeWorkflow("wf")
        self.assertIn("combine results", result["prompt"])

    def test_execute_missing_raises(self):
        with self.assertRaises(WorkflowNotFoundError):
            self.reg.executeWorkflow("does-not-exist")

    def test_execute_parallel_phase_labeled(self):
        reg = _empty_reg()
        reg.addWorkflow("par", {
            "name": "par",
            "description": "d",
            "phases": [{"title": "P", "parallel": True, "agents": []}],
            "synthesis": "s",
        })
        result = reg.executeWorkflow("par")
        self.assertIn("parallel", result["prompt"])


# ---------------------------------------------------------------------------
# Module-level REGISTRY singleton
# ---------------------------------------------------------------------------

class TestModuleLevelRegistry(unittest.TestCase):
    def test_registry_is_workflow_registry_instance(self):
        self.assertIsInstance(REGISTRY, WorkflowRegistry)

    def test_registry_is_non_empty(self):
        self.assertGreater(len(REGISTRY.listWorkflows()), 0)

    def test_registry_contains_shipped_workflows(self):
        for name in ("code_review", "bug_investigation", "feature_implementation"):
            with self.subTest(name=name):
                self.assertIn(name, REGISTRY.listWorkflows())

    def test_execute_code_review_from_singleton(self):
        result = REGISTRY.executeWorkflow("code_review", context="review main.py")
        self.assertTrue(result["ok"])
        self.assertIn("correctness", result["prompt"])

    def test_singleton_add_and_remove(self):
        wf = _valid_wf("singleton-test")
        REGISTRY.addWorkflow("singleton-test", wf)
        self.assertIn("singleton-test", REGISTRY.listWorkflows())
        REGISTRY.removeWorkflow("singleton-test")
        self.assertNotIn("singleton-test", REGISTRY.listWorkflows())
