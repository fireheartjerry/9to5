"""Tests for buildStepSpec and getDecisionPoints in agents/trace_replay.py.

Covers:
  - buildStepSpec: step-mode invocation spec builder.
  - getDecisionPoints: decision-point result packaging.

CWD-independent design: all module discovery uses Path(__file__).resolve().

Split from test_trace_replay_subagent.py (was 408 lines).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents import trace_replay as _wf  # noqa: E402

_REQUIRED_SPEC_KEYS = _wf._REQUIRED_SPEC_KEYS


# ── buildStepSpec ─────────────────────────────────────────────────────────────

@pytest.mark.test_cli_features
class TestBuildStepSpec(unittest.TestCase):

    def _spec(self, **kw) -> dict:
        return _wf.buildStepSpec(**kw)

    def test_returns_dict(self):
        self.assertIsInstance(self._spec(), dict)

    def test_has_all_required_keys(self):
        spec = self._spec()
        for key in _REQUIRED_SPEC_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, spec)

    def test_meta_mode_is_step(self):
        spec = self._spec()
        self.assertEqual(spec["_meta"]["mode"], "step")

    def test_meta_output_format_is_json(self):
        spec = self._spec()
        self.assertEqual(spec["_meta"]["output_format"], "json")

    def test_meta_color_is_false(self):
        spec = self._spec()
        self.assertFalse(spec["_meta"]["color"])

    def test_run_id_in_prompt_when_supplied(self):
        spec = self._spec(run_id="run-xyz")
        self.assertIn("run-xyz", spec["prompt"])

    def test_limit_used_when_no_run_id(self):
        spec = self._spec(limit=3)
        self.assertIn("--limit 3", spec["prompt"])

    def test_json_flag_in_prompt(self):
        spec = self._spec()
        self.assertIn("--format json", spec["prompt"])

    def test_no_color_flag_in_prompt(self):
        spec = self._spec()
        self.assertIn("--no-color", spec["prompt"])

    def test_effort_level_is_default(self):
        self.assertEqual(self._spec()["effort_level"], "default")

    def test_subagent_is_none(self):
        self.assertIsNone(self._spec()["subagent"])

    def test_calibrate_limit_stored_in_meta(self):
        spec = self._spec(calibrate_limit=15)
        self.assertEqual(spec["_meta"]["calibrate_limit"], 15)

    def test_run_id_stored_in_meta(self):
        spec = self._spec(run_id="r1")
        self.assertEqual(spec["_meta"]["run_id"], "r1")

    def test_none_run_id_stored_in_meta(self):
        spec = self._spec()
        self.assertIsNone(spec["_meta"]["run_id"])

    def test_claude_md_inject_mentions_decision_points(self):
        spec = self._spec()
        self.assertIn("decision", spec["claude_md_inject"].lower())

    def test_hooks_are_lists(self):
        spec = self._spec()
        self.assertIsInstance(spec["pre_tool_hooks"], list)
        self.assertIsInstance(spec["post_tool_hooks"], list)

    def test_differs_from_buildspec_by_meta_mode(self):
        step = _wf.buildStepSpec(run_id="r", limit=5)
        base = _wf.buildSpec(run_id="r", limit=5)
        self.assertEqual(step["_meta"]["mode"], "step")
        self.assertNotIn("mode", base["_meta"])


# ── getDecisionPoints ─────────────────────────────────────────────────────────

@pytest.mark.test_cli_features
class TestGetDecisionPoints(unittest.TestCase):

    def _run_gdp(self, run_id=None, recent=None, proc_report=None, returncode=0) -> dict:
        """Helper: patch tracing + subprocess, then call getDecisionPoints."""
        if recent is None:
            recent = []
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=recent):
            if proc_report is None:
                return _wf.getDecisionPoints(run_id=run_id)
            proc = mock.MagicMock()
            proc.returncode = returncode
            proc.stdout = json.dumps(proc_report)
            proc.stderr = ""
            with mock.patch("subprocess.run", return_value=proc):
                return _wf.getDecisionPoints(run_id=run_id)

    def _base_report(self, **overrides) -> dict:
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

    def test_returns_dict(self):
        result = self._run_gdp()
        self.assertIsInstance(result, dict)

    def test_no_traces_ok_true(self):
        result = self._run_gdp()
        self.assertTrue(result["ok"])

    def test_no_traces_empty_decision_points(self):
        result = self._run_gdp()
        self.assertEqual(result["decision_points"], [])

    def test_no_traces_total_events_zero(self):
        result = self._run_gdp()
        self.assertEqual(result["total_events"], 0)

    def test_no_traces_error_is_no_traces(self):
        result = self._run_gdp()
        self.assertEqual(result["error"], "no_traces")

    def test_required_keys_present(self):
        result = self._run_gdp()
        for key in ("ok", "run_id", "decision_points", "total_events", "error"):
            with self.subTest(key=key):
                self.assertIn(key, result)

    def test_divergences_propagated_as_decision_points(self):
        divs = [
            {"offset": "T+0.00s", "event": "verify_fail", "subtask": "s",
             "kind": "FAIL", "fields": "", "ts": 0.0},
        ]
        report = self._base_report(divergences=divs, divergence_count=1)
        result = self._run_gdp(recent=["run-001"], proc_report=report)
        self.assertTrue(result["ok"])
        self.assertEqual(result["decision_points"], divs)

    def test_total_events_propagated(self):
        report = self._base_report(total_events=9)
        result = self._run_gdp(recent=["run-001"], proc_report=report)
        self.assertEqual(result["total_events"], 9)

    def test_subprocess_error_ok_false(self):
        proc = mock.MagicMock()
        proc.returncode = 1
        proc.stdout = ""
        proc.stderr = "crash"
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=["run-001"]):
            with mock.patch("subprocess.run", return_value=proc):
                result = _wf.getDecisionPoints()
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])

    def test_subprocess_timeout_ok_false(self):
        import subprocess as _sp
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=["run-001"]):
            with mock.patch("subprocess.run", side_effect=_sp.TimeoutExpired("cmd", 60)):
                result = _wf.getDecisionPoints()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "timeout")

    def test_run_id_propagated(self):
        report = self._base_report(run_id="my-run")
        result = self._run_gdp(recent=["my-run"], proc_report=report)
        self.assertEqual(result["run_id"], "my-run")

    def test_empty_divergences_gives_empty_decision_points(self):
        report = self._base_report(divergences=[])
        result = self._run_gdp(recent=["run-001"], proc_report=report)
        self.assertTrue(result["ok"])
        self.assertEqual(result["decision_points"], [])


if __name__ == "__main__":
    _loader = unittest.TestLoader()
    _suite = unittest.TestSuite([
        _loader.loadTestsFromTestCase(TestBuildStepSpec),
        _loader.loadTestsFromTestCase(TestGetDecisionPoints),
    ])
    _result = unittest.TextTestRunner(verbosity=2).run(_suite)
    sys.exit(0 if _result.wasSuccessful() else 1)
