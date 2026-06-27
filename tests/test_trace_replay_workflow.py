"""Tests for agents/trace_replay.py optimized workflow.

Validates the invocation spec structure, buildSpec() output, and
runWorkflow() behaviour (mocked for subprocess / tracing calls).

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
        # When a run_id is supplied and tracing returns nothing, we still proceed
        # to subprocess — mock subprocess to avoid real exec.
        fake_json = json.dumps({
            "run_id": "explicit-run",
            "divergence_count": 0,
            "high_activity_count": 0,
            "parallel_moments": 0,
            "total_events": 1,
            "divergences": [],
        })
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = fake_json
        proc.stderr = ""
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=[]):
            with mock.patch("subprocess.run", return_value=proc):
                result = _wf.runWorkflow(run_id="explicit-run")
        self.assertTrue(result["ok"])
        self.assertEqual(result["run_id"], "explicit-run")


# ── runWorkflow — subprocess path ─────────────────────────────────────────────

class TestRunWorkflowSubprocess(unittest.TestCase):

    def _make_proc(self, report: dict, returncode: int = 0) -> mock.MagicMock:
        proc = mock.MagicMock()
        proc.returncode = returncode
        proc.stdout = json.dumps(report)
        proc.stderr = ""
        return proc

    def _run(self, report: dict, returncode: int = 0, recent=None, **kw) -> dict:
        if recent is None:
            recent = ["run-001"]
        proc = self._make_proc(report, returncode)
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=recent):
            with mock.patch("subprocess.run", return_value=proc):
                return _wf.runWorkflow(**kw)

    def _report(self, **overrides) -> dict:
        base = {
            "run_id": "run-001",
            "divergence_count": 0,
            "high_activity_count": 0,
            "parallel_moments": 0,
            "total_events": 2,
            "divergences": [],
        }
        base.update(overrides)
        return base

    def test_clean_run_ok(self):
        result = self._run(self._report())
        self.assertTrue(result["ok"])
        self.assertIsNone(result["error"])

    def test_divergence_count_propagated(self):
        result = self._run(self._report(divergence_count=3))
        self.assertEqual(result["divergence_count"], 3)

    def test_high_activity_count_propagated(self):
        result = self._run(self._report(high_activity_count=2))
        self.assertEqual(result["high_activity_count"], 2)

    def test_total_events_propagated(self):
        result = self._run(self._report(total_events=7))
        self.assertEqual(result["total_events"], 7)

    def test_divergences_list_propagated(self):
        divs = [{"offset": "T+0.00s", "event": "verify_fail", "subtask": "s", "kind": "FAIL"}]
        result = self._run(self._report(divergences=divs, divergence_count=1))
        self.assertEqual(result["divergences"], divs)

    def test_subprocess_error_captured(self):
        proc = mock.MagicMock()
        proc.returncode = 1
        proc.stdout = ""
        proc.stderr = "something failed"
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=["run-001"]):
            with mock.patch("subprocess.run", return_value=proc):
                result = _wf.runWorkflow()
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])

    def test_json_parse_error_captured(self):
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = "not json at all"
        proc.stderr = ""
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=["run-001"]):
            with mock.patch("subprocess.run", return_value=proc):
                result = _wf.runWorkflow()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "json_parse_error")

    def test_timeout_captured(self):
        import subprocess as _sp
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=["run-001"]):
            with mock.patch("subprocess.run", side_effect=_sp.TimeoutExpired("cmd", 60)):
                result = _wf.runWorkflow()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "timeout")

    def test_run_id_resolved_from_json(self):
        result = self._run(self._report(run_id="resolved-run"))
        self.assertEqual(result["run_id"], "resolved-run")

    def test_log_prefix_before_json_handled(self):
        # Script may emit log lines before the JSON block; parser must skip them.
        report = self._report(divergence_count=1)
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = "[trace-replay] Calibrated threshold=10 from 2 run(s)\n" + json.dumps(report)
        proc.stderr = ""
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=["run-001"]):
            with mock.patch("subprocess.run", return_value=proc):
                result = _wf.runWorkflow()
        self.assertTrue(result["ok"])
        self.assertEqual(result["divergence_count"], 1)


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

    def test_no_traces_does_not_spawn_subprocess(self):
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=[]):
            with mock.patch("subprocess.run") as mock_run:
                _wf.runWorkflow()
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
