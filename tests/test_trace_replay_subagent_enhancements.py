"""Tests for agents/trace_replay.py subagent enhancements.

Covers the public API of the trace_replay workflow module:
  - DEFAULT_INVOCATION_SPEC structure
  - buildSpec()
  - runWorkflow()        (subprocess mocked)
  - buildStepSpec()      (enhancement)
  - getDecisionPoints()  (enhancement)

Acceptance command: python C:\\9to5\\tests\\test_trace_replay_subagent_enhancements.py
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


# ── runWorkflow (mocked subprocess) ──────────────────────────────────────────

def _make_proc(stdout: str, returncode: int = 0, stderr: str = "") -> mock.MagicMock:
    proc = mock.MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


_GOOD_JSON = json.dumps({
    "run_id": "run_good",
    "total_events": 8,
    "divergence_count": 2,
    "high_activity_count": 1,
    "parallel_moments": 0,
    "divergences": [
        {
            "offset": "T+1.00s",
            "event": "executor_failed",
            "subtask": "st-001",
            "kind": "FAIL",
            "fields": "exit_code='1'",
            "ts": 1000.0,
        }
    ],
})


class TestRunWorkflow(unittest.TestCase):

    def _patch(self, recent=None, proc=None):
        """Return a context manager that patches tracing.recentRunIds and subprocess.run."""
        if recent is None:
            recent = ["run_good"]
        if proc is None:
            proc = _make_proc(_GOOD_JSON)
        patches = [
            mock.patch.object(tr.tracing, "recentRunIds", return_value=recent),
            mock.patch("subprocess.run", return_value=proc),
        ]
        return patches

    def test_ok_true_on_success(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", return_value=_make_proc(_GOOD_JSON)):
            result = tr.runWorkflow()
        self.assertTrue(result["ok"])

    def test_divergence_count_parsed(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", return_value=_make_proc(_GOOD_JSON)):
            result = tr.runWorkflow()
        self.assertEqual(result["divergence_count"], 2)

    def test_high_activity_count_parsed(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", return_value=_make_proc(_GOOD_JSON)):
            result = tr.runWorkflow()
        self.assertEqual(result["high_activity_count"], 1)

    def test_total_events_parsed(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", return_value=_make_proc(_GOOD_JSON)):
            result = tr.runWorkflow()
        self.assertEqual(result["total_events"], 8)

    def test_divergences_list_parsed(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", return_value=_make_proc(_GOOD_JSON)):
            result = tr.runWorkflow()
        self.assertIsInstance(result["divergences"], list)
        self.assertEqual(len(result["divergences"]), 1)

    def test_error_is_none_on_success(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", return_value=_make_proc(_GOOD_JSON)):
            result = tr.runWorkflow()
        self.assertIsNone(result["error"])

    def test_no_traces_returns_no_traces_error(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=[]):
            result = tr.runWorkflow()
        self.assertEqual(result["error"], "no_traces")
        self.assertTrue(result["ok"])

    def test_no_traces_divergence_count_zero(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=[]):
            result = tr.runWorkflow()
        self.assertEqual(result["divergence_count"], 0)

    def test_subprocess_nonzero_exit_sets_ok_false(self):
        proc = _make_proc("", returncode=1, stderr="some error")
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", return_value=proc):
            result = tr.runWorkflow()
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])

    def test_timeout_sets_ok_false(self):
        import subprocess as sp
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", side_effect=sp.TimeoutExpired(cmd=[], timeout=60)):
            result = tr.runWorkflow()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "timeout")

    def test_json_parse_error_sets_ok_false(self):
        proc = _make_proc("not valid json at all")
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", return_value=proc):
            result = tr.runWorkflow()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "json_parse_error")

    def test_json_after_log_lines_parsed(self):
        # Script may emit log lines before the JSON object.
        stdout_with_preamble = "INFO loading trace\nDEBUG calibrating\n" + _GOOD_JSON
        proc = _make_proc(stdout_with_preamble)
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", return_value=proc):
            result = tr.runWorkflow()
        self.assertTrue(result["ok"])
        self.assertEqual(result["divergence_count"], 2)

    def test_explicit_run_id_skips_recent_check(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=[]) as mock_recent, \
             mock.patch("subprocess.run", return_value=_make_proc(_GOOD_JSON)):
            result = tr.runWorkflow(run_id="explicit_run")
        # recentRunIds still called (fast-path only fires when run_id is None)
        # The key assertion: result was ok despite empty recent list.
        self.assertTrue(result["ok"])

    def test_result_has_raw_key(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", return_value=_make_proc(_GOOD_JSON)):
            result = tr.runWorkflow()
        self.assertIn("raw", result)

    def test_parallel_moments_parsed(self):
        payload = dict(json.loads(_GOOD_JSON))
        payload["parallel_moments"] = 3
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", return_value=_make_proc(json.dumps(payload))):
            result = tr.runWorkflow()
        self.assertEqual(result["parallel_moments"], 3)


# ── getDecisionPoints (enhancement) ──────────────────────────────────────────

class TestGetDecisionPoints(unittest.TestCase):

    def _run_with_good_json(self, **kwargs):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", return_value=_make_proc(_GOOD_JSON)):
            return tr.getDecisionPoints(**kwargs)

    def test_ok_true_on_success(self):
        result = self._run_with_good_json()
        self.assertTrue(result["ok"])

    def test_decision_points_key_present(self):
        result = self._run_with_good_json()
        self.assertIn("decision_points", result)

    def test_decision_points_is_list(self):
        result = self._run_with_good_json()
        self.assertIsInstance(result["decision_points"], list)

    def test_decision_points_matches_divergences(self):
        result = self._run_with_good_json()
        raw = json.loads(_GOOD_JSON)
        self.assertEqual(len(result["decision_points"]), len(raw["divergences"]))

    def test_total_events_propagated(self):
        result = self._run_with_good_json()
        self.assertEqual(result["total_events"], 8)

    def test_run_id_propagated(self):
        result = self._run_with_good_json()
        self.assertEqual(result["run_id"], "run_good")

    def test_error_none_on_success(self):
        result = self._run_with_good_json()
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

    def test_subprocess_failure_propagates(self):
        proc = _make_proc("", returncode=1, stderr="kaboom")
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", return_value=proc):
            result = tr.getDecisionPoints()
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])

    def test_decision_points_entry_has_kind(self):
        result = self._run_with_good_json()
        for dp in result["decision_points"]:
            with self.subTest(dp=dp):
                self.assertIn("kind", dp)

    def test_decision_points_entry_has_event(self):
        result = self._run_with_good_json()
        for dp in result["decision_points"]:
            with self.subTest(dp=dp):
                self.assertIn("event", dp)

    def test_explicit_run_id_forwarded(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=[]) as m_recent, \
             mock.patch("subprocess.run", return_value=_make_proc(_GOOD_JSON)):
            result = tr.getDecisionPoints(run_id="explicit_dp")
        self.assertTrue(result["ok"])

    def test_limit_param_accepted(self):
        result = self._run_with_good_json(limit=3)
        self.assertIn("decision_points", result)

    def test_calibrate_limit_param_accepted(self):
        result = self._run_with_good_json(calibrate_limit=5)
        self.assertIn("decision_points", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
