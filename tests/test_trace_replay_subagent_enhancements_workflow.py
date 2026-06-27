"""Tests for agents/trace_replay.py – runWorkflow and getDecisionPoints.

Covers:
  - runWorkflow()        (subprocess mocked)
  - getDecisionPoints()  (enhancement)

Split from test_trace_replay_subagent_enhancements.py (was 431 lines).
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


# ── Helpers ───────────────────────────────────────────────────────────────────

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


# ── runWorkflow (mocked subprocess) ──────────────────────────────────────────

class TestRunWorkflow(unittest.TestCase):

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
        stdout_with_preamble = "INFO loading trace\nDEBUG calibrating\n" + _GOOD_JSON
        proc = _make_proc(stdout_with_preamble)
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=["r1"]), \
             mock.patch("subprocess.run", return_value=proc):
            result = tr.runWorkflow()
        self.assertTrue(result["ok"])
        self.assertEqual(result["divergence_count"], 2)

    def test_explicit_run_id_skips_recent_check(self):
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=[]), \
             mock.patch("subprocess.run", return_value=_make_proc(_GOOD_JSON)):
            result = tr.runWorkflow(run_id="explicit_run")
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
        with mock.patch.object(tr.tracing, "recentRunIds", return_value=[]), \
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
