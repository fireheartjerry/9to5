"""Tests for agents/trace_replay.py – invocation spec builders.

Covers:
  - DEFAULT_INVOCATION_SPEC structure
  - buildSpec()
  - buildStepSpec()      (enhancement)

Split from test_trace_replay_subagent_enhancements.py (was 431 lines).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import agents.trace_replay as tr

_REQUIRED_SPEC_KEYS = frozenset({
    "claude_md_inject",
    "skills_to_invoke",
    "effort_level",
    "subagent",
    "prompt",
    "pre_tool_hooks",
    "post_tool_hooks",
})


# ── DEFAULT_INVOCATION_SPEC ────────────────────────────────────────────────────

class TestDefaultInvocationSpec(unittest.TestCase):

    def test_has_all_required_keys(self):
        for key in _REQUIRED_SPEC_KEYS:
            self.assertIn(key, tr.DEFAULT_INVOCATION_SPEC, msg=f"missing key: {key}")

    def test_skills_to_invoke_is_list(self):
        self.assertIsInstance(tr.DEFAULT_INVOCATION_SPEC["skills_to_invoke"], list)

    def test_pre_tool_hooks_is_list(self):
        self.assertIsInstance(tr.DEFAULT_INVOCATION_SPEC["pre_tool_hooks"], list)

    def test_post_tool_hooks_contains_write_obsidian(self):
        self.assertIn("write_obsidian", tr.DEFAULT_INVOCATION_SPEC["post_tool_hooks"])

    def test_effort_level_is_string(self):
        self.assertIsInstance(tr.DEFAULT_INVOCATION_SPEC["effort_level"], str)

    def test_prompt_mentions_json_flag(self):
        self.assertIn("json", tr.DEFAULT_INVOCATION_SPEC["prompt"].lower())


# ── buildSpec ─────────────────────────────────────────────────────────────────

class TestBuildSpec(unittest.TestCase):

    def test_returns_all_required_keys(self):
        spec = tr.buildSpec()
        for key in _REQUIRED_SPEC_KEYS:
            self.assertIn(key, spec, msg=f"missing key: {key}")

    def test_meta_present(self):
        spec = tr.buildSpec()
        self.assertIn("_meta", spec)

    def test_meta_run_id_none_by_default(self):
        spec = tr.buildSpec()
        self.assertIsNone(spec["_meta"]["run_id"])

    def test_meta_run_id_set_when_provided(self):
        spec = tr.buildSpec(run_id="run_abc")
        self.assertEqual(spec["_meta"]["run_id"], "run_abc")

    def test_meta_limit_default(self):
        spec = tr.buildSpec()
        self.assertEqual(spec["_meta"]["limit"], 5)

    def test_meta_limit_custom(self):
        spec = tr.buildSpec(limit=10)
        self.assertEqual(spec["_meta"]["limit"], 10)

    def test_meta_calibrate_limit_default(self):
        spec = tr.buildSpec()
        self.assertEqual(spec["_meta"]["calibrate_limit"], 20)

    def test_meta_calibrate_limit_custom(self):
        spec = tr.buildSpec(calibrate_limit=5)
        self.assertEqual(spec["_meta"]["calibrate_limit"], 5)

    def test_meta_output_format_json(self):
        spec = tr.buildSpec()
        self.assertEqual(spec["_meta"]["output_format"], "json")

    def test_meta_color_false(self):
        spec = tr.buildSpec()
        self.assertFalse(spec["_meta"]["color"])

    def test_prompt_includes_run_id_clause(self):
        spec = tr.buildSpec(run_id="run_xyz")
        self.assertIn("run_xyz", spec["prompt"])

    def test_prompt_includes_limit_clause_when_no_run_id(self):
        spec = tr.buildSpec(limit=7)
        self.assertIn("7", spec["prompt"])

    def test_prompt_always_includes_json_flag(self):
        for spec in (tr.buildSpec(), tr.buildSpec(run_id="r1")):
            with self.subTest(spec=spec["prompt"]):
                self.assertIn("json", spec["prompt"])

    def test_post_tool_hooks_has_write_obsidian(self):
        spec = tr.buildSpec()
        self.assertIn("write_obsidian", spec["post_tool_hooks"])

    def test_skills_to_invoke_empty_list(self):
        spec = tr.buildSpec()
        self.assertEqual(spec["skills_to_invoke"], [])


# ── buildStepSpec (enhancement) ───────────────────────────────────────────────

class TestBuildStepSpec(unittest.TestCase):

    def test_returns_all_required_keys(self):
        spec = tr.buildStepSpec()
        for key in _REQUIRED_SPEC_KEYS:
            self.assertIn(key, spec, msg=f"missing key: {key}")

    def test_meta_mode_is_step(self):
        spec = tr.buildStepSpec()
        self.assertEqual(spec["_meta"]["mode"], "step")

    def test_meta_run_id_none_by_default(self):
        spec = tr.buildStepSpec()
        self.assertIsNone(spec["_meta"]["run_id"])

    def test_meta_run_id_propagated(self):
        spec = tr.buildStepSpec(run_id="run_step_42")
        self.assertEqual(spec["_meta"]["run_id"], "run_step_42")

    def test_meta_calibrate_limit_propagated(self):
        spec = tr.buildStepSpec(calibrate_limit=7)
        self.assertEqual(spec["_meta"]["calibrate_limit"], 7)

    def test_claude_md_inject_mentions_decision_point(self):
        spec = tr.buildStepSpec()
        self.assertIn("decision", spec["claude_md_inject"].lower())

    def test_claude_md_inject_mentions_context_before_or_after(self):
        inject = tr.buildStepSpec()["claude_md_inject"]
        self.assertTrue(
            "context_before" in inject or "context_after" in inject,
            msg="step spec should mention context_before or context_after",
        )

    def test_prompt_includes_json_flag(self):
        spec = tr.buildStepSpec()
        self.assertIn("json", spec["prompt"])

    def test_prompt_includes_run_id_when_given(self):
        spec = tr.buildStepSpec(run_id="run_s1")
        self.assertIn("run_s1", spec["prompt"])

    def test_post_tool_hooks_has_write_obsidian(self):
        spec = tr.buildStepSpec()
        self.assertIn("write_obsidian", spec["post_tool_hooks"])

    def test_meta_output_format_json(self):
        spec = tr.buildStepSpec()
        self.assertEqual(spec["_meta"]["output_format"], "json")

    def test_meta_color_false(self):
        spec = tr.buildStepSpec()
        self.assertFalse(spec["_meta"]["color"])

    def test_differs_from_build_spec_in_mode(self):
        plain = tr.buildSpec(run_id="r")
        step = tr.buildStepSpec(run_id="r")
        self.assertNotEqual(
            plain["claude_md_inject"],
            step["claude_md_inject"],
        )
        self.assertEqual(step["_meta"]["mode"], "step")


if __name__ == "__main__":
    unittest.main(verbosity=2)
