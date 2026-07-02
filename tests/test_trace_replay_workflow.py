"""Tests for agents/trace_replay.py optimized workflow.

Validates the invocation spec structure, buildSpec() output, and
runWorkflow() behaviour (tracing calls mocked; replay runs in-process).

Acceptance command: python C:\\9to5\\tests\\test_trace_replay_workflow.py
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

from agents import trace_replay as _wf  # noqa: E402

_REQUIRED_SPEC_KEYS = _wf._REQUIRED_SPEC_KEYS


# ── DEFAULT_INVOCATION_SPEC ────────────────────────────────────────────────────

class TestDefaultInvocationSpec(unittest.TestCase):

    def test_has_all_required_keys(self):
        for key in _REQUIRED_SPEC_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, _wf.DEFAULT_INVOCATION_SPEC)

    def test_effort_level_is_valid(self):
        valid = {"default", "high", "xhigh", "ultracode"}
        self.assertIn(_wf.DEFAULT_INVOCATION_SPEC["effort_level"], valid)

    def test_skills_to_invoke_is_list(self):
        self.assertIsInstance(_wf.DEFAULT_INVOCATION_SPEC["skills_to_invoke"], list)

    def test_hooks_are_lists(self):
        self.assertIsInstance(_wf.DEFAULT_INVOCATION_SPEC["pre_tool_hooks"], list)
        self.assertIsInstance(_wf.DEFAULT_INVOCATION_SPEC["post_tool_hooks"], list)

    def test_prompt_is_non_empty_string(self):
        prompt = _wf.DEFAULT_INVOCATION_SPEC["prompt"]
        self.assertIsInstance(prompt, str)
        self.assertTrue(len(prompt) > 0)

    def test_claude_md_inject_is_string(self):
        self.assertIsInstance(_wf.DEFAULT_INVOCATION_SPEC["claude_md_inject"], str)


# ── buildSpec ─────────────────────────────────────────────────────────────────

class TestBuildSpec(unittest.TestCase):

    def _spec(self, **kw) -> dict:
        return _wf.buildSpec(**kw)

    def test_returns_dict(self):
        self.assertIsInstance(self._spec(), dict)

    def test_has_all_required_keys(self):
        spec = self._spec()
        for key in _REQUIRED_SPEC_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, spec)

    def test_default_output_format_is_json(self):
        spec = self._spec()
        self.assertIn("--format json", spec["prompt"])

    def test_no_color_flag_present(self):
        spec = self._spec()
        self.assertIn("--no-color", spec["prompt"])

    def test_run_id_injected_into_prompt(self):
        spec = self._spec(run_id="run-abc123")
        self.assertIn("run-abc123", spec["prompt"])

    def test_no_run_id_uses_limit(self):
        spec = self._spec(limit=3)
        self.assertIn("--limit 3", spec["prompt"])

    def test_meta_block_present(self):
        spec = self._spec(run_id="r1", calibrate_limit=10)
        self.assertIn("_meta", spec)
        self.assertEqual(spec["_meta"]["run_id"], "r1")
        self.assertEqual(spec["_meta"]["calibrate_limit"], 10)
        self.assertFalse(spec["_meta"]["color"])
        self.assertEqual(spec["_meta"]["output_format"], "json")

    def test_effort_level_is_default(self):
        # Trace replay is lightweight — should not use high or ultracode effort.
        self.assertEqual(self._spec()["effort_level"], "default")

    def test_subagent_is_none(self):
        self.assertIsNone(self._spec()["subagent"])

    def test_calibrate_limit_stored_in_meta(self):
        spec = self._spec(calibrate_limit=5)
        self.assertEqual(spec["_meta"]["calibrate_limit"], 5)

    def test_limit_stored_in_meta(self):
        spec = self._spec(limit=7)
        self.assertEqual(spec["_meta"]["limit"], 7)


# ── runWorkflow — no-trace fast path ─────────────────────────────────────────

class TestRunWorkflowNoTraces(unittest.TestCase):

    def _run(self, recent=None, **kw) -> dict:
        if recent is None:
            recent = []
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=recent):
            return _wf.runWorkflow(**kw)

    def test_returns_dict(self):
        result = self._run()
        self.assertIsInstance(result, dict)

    def test_no_traces_fast_path_ok_true(self):
        result = self._run()
        self.assertTrue(result["ok"])

    def test_no_traces_error_is_no_traces(self):
        result = self._run()
        self.assertEqual(result["error"], "no_traces")

    def test_no_traces_zero_divergences(self):
        result = self._run()
        self.assertEqual(result["divergence_count"], 0)

    def test_no_traces_total_events_zero(self):
        result = self._run()
        self.assertEqual(result["total_events"], 0)

    def test_no_traces_divergences_list_empty(self):
        result = self._run()
        self.assertIsInstance(result["divergences"], list)
        self.assertEqual(len(result["divergences"]), 0)

    def test_explicit_run_id_skips_tracing_check(self):
        # When a run_id is supplied and tracing returns nothing, we still replay
        # that run's events in-process.
        events = [_ev("run_completed", "st-A", 0)]
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=[]):
            with mock.patch.object(_wf.tracing, "readEvents", return_value=events):
                result = _wf.runWorkflow(run_id="explicit-run")
        self.assertTrue(result["ok"])
        self.assertEqual(result["run_id"], "explicit-run")


# ── runWorkflow — in-process replay path ─────────────────────────────────────

def _ev(event: str, subtask: str, second: int) -> dict:
    return {
        "ts": f"2026-01-01T00:00:{second:02d}+00:00",
        "run_id": "run-001",
        "subtask_id": subtask,
        "event": event,
    }


class TestRunWorkflowInProcess(unittest.TestCase):

    def _run(self, events: list, recent=None, **kw) -> dict:
        if recent is None:
            recent = ["run-001"]
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=recent):
            with mock.patch.object(_wf.tracing, "readEvents", return_value=events):
                return _wf.runWorkflow(**kw)

    def test_clean_run_ok(self):
        result = self._run([_ev("run_completed", "st-A", 0), _ev("verify_passed", "st-A", 1)])
        self.assertTrue(result["ok"])
        self.assertIsNone(result["error"])
        self.assertEqual(result["divergence_count"], 0)

    def test_divergence_count_computed(self):
        events = [
            _ev("verification_failed", "st-A", 0),
            _ev("replan_triggered", "st-A", 1),
            _ev("adversary_challenged", "st-B", 2),
            _ev("verify_passed", "st-B", 3),
        ]
        result = self._run(events)
        self.assertEqual(result["divergence_count"], 3)

    def test_total_events_computed(self):
        events = [_ev("verify_passed", "st-A", i) for i in range(7)]
        result = self._run(events)
        self.assertEqual(result["total_events"], 7)

    def test_high_activity_count_computed(self):
        # 12 events in one subtask exceeds the fallback threshold of 10.
        # No calibration runs (recent=[]) so the fallback threshold applies.
        events = [_ev("step_started", "st-busy", i) for i in range(12)]
        result = self._run(events, recent=[], run_id="run-001")
        self.assertEqual(result["high_activity_count"], 1)

    def test_divergence_entries_have_expected_fields(self):
        result = self._run([_ev("verification_failed", "st-A", 0)])
        self.assertEqual(len(result["divergences"]), 1)
        entry = result["divergences"][0]
        for key in ("offset", "event", "subtask", "kind"):
            self.assertIn(key, entry)
        self.assertEqual(entry["kind"], "FAIL")

    def test_read_error_captured(self):
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=["run-001"]):
            with mock.patch.object(_wf.tracing, "readEvents",
                                   side_effect=RuntimeError("disk gone")):
                result = _wf.runWorkflow()
        self.assertFalse(result["ok"])
        self.assertIn("disk gone", result["error"])

    def test_no_events_for_run(self):
        result = self._run([])
        self.assertTrue(result["ok"])
        self.assertEqual(result["error"], "no_events")
        self.assertEqual(result["run_id"], "run-001")

    def test_run_id_resolved_from_recent(self):
        result = self._run([_ev("verify_passed", "st-A", 0)], recent=["resolved-run"])
        self.assertEqual(result["run_id"], "resolved-run")

    def test_raw_is_json_report(self):
        result = self._run([_ev("verification_failed", "st-A", 0)])
        report = json.loads(result["raw"])
        self.assertEqual(report["divergence_count"], 1)


# ── Optimization properties ───────────────────────────────────────────────────

class TestWorkflowOptimizations(unittest.TestCase):
    """Verify the key efficiency invariants of the optimized workflow."""

    def test_spec_always_requests_json_output(self):
        for run_id in (None, "run-x"):
            spec = _wf.buildSpec(run_id=run_id)
            self.assertIn("--format json", spec["prompt"],
                          f"JSON output must always be requested (run_id={run_id!r})")

    def test_spec_always_disables_color(self):
        for run_id in (None, "run-x"):
            spec = _wf.buildSpec(run_id=run_id)
            self.assertIn("--no-color", spec["prompt"],
                          f"--no-color must always be present (run_id={run_id!r})")

    def test_calibrate_limit_defaults_to_20(self):
        spec = _wf.buildSpec()
        self.assertEqual(spec["_meta"]["calibrate_limit"], 20)

    def test_no_traces_does_not_read_events(self):
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=[]):
            with mock.patch.object(_wf.tracing, "readEvents") as mock_read:
                _wf.runWorkflow()
        mock_read.assert_not_called()
