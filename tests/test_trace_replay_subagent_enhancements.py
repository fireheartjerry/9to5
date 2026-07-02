"""Tests for agents/trace_replay.py – invocation spec builders, runWorkflow, getDecisionPoints.

Covers:
  spec:
  - DEFAULT_INVOCATION_SPEC structure
  - buildSpec()
  - buildStepSpec()      (enhancement)

  workflow:
  - runWorkflow()        (tracing mocked; replay runs in-process)
  - getDecisionPoints()  (enhancement)
"""
from __future__ import annotations

import json
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ev(event: str, subtask: str, second: int) -> dict:
    return {
        "ts": f"2026-01-01T00:00:{second:02d}+00:00",
        "run_id": "r1",
        "subtask_id": subtask,
        "event": event,
    }


# 8 events, 2 divergences (both FAIL), no high-activity subtask, no parallel moments.
_GOOD_EVENTS: list = [
    _ev("run_started", "st-001", 0),
    _ev("executor_failed", "st-001", 1),
    _ev("verification_failed", "st-001", 2),
    _ev("verify_passed", "st-001", 3),
    _ev("step_started", "st-002", 4),
    _ev("step_finished", "st-002", 5),
    _ev("verify_passed", "st-002", 6),
    _ev("run_completed", "st-002", 7),
]


def _patch_tracing(events=_GOOD_EVENTS, recent=("r1",)):
    """Patch both tracing seams used by the in-process replay."""
    return (
        mock.patch.object(tr.tracing, "recentRunIds", return_value=list(recent)),
        mock.patch.object(tr.tracing, "readEvents", return_value=events),
    )


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


# ── runWorkflow (in-process replay, tracing mocked) ──────────────────────────

class TestRunWorkflow(unittest.TestCase):

    def _run(self, events=_GOOD_EVENTS, recent=("r1",), **kw) -> dict:
        p_recent, p_read = _patch_tracing(events, recent)
        with p_recent, p_read:
            return tr.runWorkflow(**kw)

    def test_ok_true_on_success(self):
        self.assertTrue(self._run()["ok"])

    def test_divergence_count_computed(self):
        self.assertEqual(self._run()["divergence_count"], 2)

    def test_high_activity_count_computed(self):
        # 12 events in one subtask exceeds the fallback threshold of 10.
        # No calibration runs (recent=()) so the fallback threshold applies.
        busy = [_ev("step_started", "st-busy", i) for i in range(12)]
        result = self._run(events=busy, recent=(), run_id="r1")
        self.assertEqual(result["high_activity_count"], 1)

    def test_total_events_computed(self):
        self.assertEqual(self._run()["total_events"], 8)

    def test_divergences_list_computed(self):
        result = self._run()
        self.assertIsInstance(result["divergences"], list)
        self.assertEqual(len(result["divergences"]), 2)

    def test_error_is_none_on_success(self):
        self.assertIsNone(self._run()["error"])

    def test_no_traces_returns_no_traces_error(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=[]):
            result = tr.runWorkflow()
        self.assertEqual(result["error"], "no_traces")
        self.assertTrue(result["ok"])

    def test_no_traces_divergence_count_zero(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=[]):
            result = tr.runWorkflow()
        self.assertEqual(result["divergence_count"], 0)

    def test_read_error_sets_ok_false(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch.object(tr.tracing, "readEvents", side_effect=OSError("some error")):
            result = tr.runWorkflow()
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])

    def test_malformed_events_do_not_crash(self):
        weird = [{"event": "verify_passed"}, {"ts": "not-a-ts", "event": "x"}, {}]
        result = self._run(events=weird)
        self.assertTrue(result["ok"])
        self.assertEqual(result["total_events"], 3)

    def test_explicit_run_id_skips_recent_check(self):
        result = self._run(recent=(), run_id="explicit_run")
        self.assertTrue(result["ok"])
        self.assertEqual(result["run_id"], "explicit_run")

    def test_result_has_raw_key(self):
        result = self._run()
        self.assertIn("raw", result)
        self.assertEqual(json.loads(result["raw"])["divergence_count"], 2)

    def test_parallel_moments_computed(self):
        # Two subtasks emitting at the same timestamp -> one parallel moment.
        events = [
            _ev("step_started", "st-A", 1),
            _ev("step_started", "st-B", 1),
            _ev("verify_passed", "st-A", 2),
        ]
        result = self._run(events=events)
        self.assertEqual(result["parallel_moments"], 1)


# ── getDecisionPoints (enhancement) ──────────────────────────────────────────

class TestGetDecisionPoints(unittest.TestCase):

    def _run_with_good_events(self, **kwargs):
        p_recent, p_read = _patch_tracing()
        with p_recent, p_read:
            return tr.getDecisionPoints(**kwargs)

    def test_ok_true_on_success(self):
        result = self._run_with_good_events()
        self.assertTrue(result["ok"])

    def test_decision_points_key_present(self):
        result = self._run_with_good_events()
        self.assertIn("decision_points", result)

    def test_decision_points_is_list(self):
        result = self._run_with_good_events()
        self.assertIsInstance(result["decision_points"], list)

    def test_decision_points_matches_divergences(self):
        result = self._run_with_good_events()
        self.assertEqual(len(result["decision_points"]), 2)

    def test_total_events_propagated(self):
        result = self._run_with_good_events()
        self.assertEqual(result["total_events"], 8)

    def test_run_id_propagated(self):
        result = self._run_with_good_events()
        self.assertEqual(result["run_id"], "r1")

    def test_error_none_on_success(self):
        result = self._run_with_good_events()
        self.assertIsNone(result["error"])

    def test_no_traces_returns_empty_decision_points(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=[]):
            result = tr.getDecisionPoints()
        self.assertEqual(result["decision_points"], [])

    def test_no_traces_ok_true(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=[]):
            result = tr.getDecisionPoints()
        self.assertTrue(result["ok"])

    def test_no_traces_error_is_no_traces(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=[]):
            result = tr.getDecisionPoints()
        self.assertEqual(result["error"], "no_traces")

    def test_read_failure_propagates(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch.object(tr.tracing, "readEvents", side_effect=OSError("kaboom")):
            result = tr.getDecisionPoints()
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])

    def test_decision_points_entry_has_kind(self):
        result = self._run_with_good_events()
        for dp in result["decision_points"]:
            with self.subTest(dp=dp):
                self.assertIn("kind", dp)

    def test_decision_points_entry_has_event(self):
        result = self._run_with_good_events()
        for dp in result["decision_points"]:
            with self.subTest(dp=dp):
                self.assertIn("event", dp)

    def test_explicit_run_id_forwarded(self):
        result = self._run_with_good_events(run_id="explicit_dp")
        self.assertTrue(result["ok"])
        self.assertEqual(result["run_id"], "explicit_dp")

    def test_limit_param_accepted(self):
        result = self._run_with_good_events(limit=3)
        self.assertIn("decision_points", result)

    def test_calibrate_limit_param_accepted(self):
        result = self._run_with_good_events(calibrate_limit=5)
        self.assertIn("decision_points", result)
