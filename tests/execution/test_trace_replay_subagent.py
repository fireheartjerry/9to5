"""Tests for agents/trace_replay_cli.py (CLI) and agents/trace_replay.py — merged.

Covers:
  extract:
  - _extractDecisionPoints in agents/trace_replay_cli.py (CLI module)

  spec_gdp:
  - buildStepSpec: step-mode invocation spec builder.
  - getDecisionPoints: decision-point result packaging.

CWD-independent design: all module discovery uses Path(__file__).resolve().
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Load trace-replay.py CLI module (hyphenated filename requires spec loader).
_cli_spec = importlib.util.spec_from_file_location(
    "trace_replay_cli", _ROOT / "agents" / "trace_replay_cli.py"
)
_cli = importlib.util.module_from_spec(_cli_spec)
_cli_spec.loader.exec_module(_cli)

_extractDecisionPoints = _cli._extractDecisionPoints

from agents import trace_replay as _wf  # noqa: E402

_REQUIRED_SPEC_KEYS = _wf._REQUIRED_SPEC_KEYS


# ── Fixtures ──────────────────────────────────────────────────────────────────

_T0 = "2026-01-01T00:00:00+00:00"
_T1 = "2026-01-01T00:00:01+00:00"
_T2 = "2026-01-01T00:00:02+00:00"
_T3 = "2026-01-01T00:00:03+00:00"
_T4 = "2026-01-01T00:00:04+00:00"
_T5 = "2026-01-01T00:00:05+00:00"
_T6 = "2026-01-01T00:00:06+00:00"

# Mixed trace: 4 divergences among 7 events.
_MIXED: list[dict] = [
    {"ts": _T0, "run_id": "m", "subtask_id": "st-A", "event": "verification_failed"},
    {"ts": _T1, "run_id": "m", "subtask_id": "st-A", "event": "replan_triggered"},
    {"ts": _T2, "run_id": "m", "subtask_id": "st-B", "event": "adversary_challenged"},
    {"ts": _T3, "run_id": "m", "subtask_id": "st-B", "event": "executor_failed"},
    {"ts": _T4, "run_id": "m", "subtask_id": "st-C", "event": "run_completed"},
    {"ts": _T5, "run_id": "m", "subtask_id": "st-C", "event": "verify_passed"},
    {"ts": _T6, "run_id": "m", "subtask_id": "st-C", "event": "verify_passed"},
]

_CLEAN: list[dict] = [
    {"ts": _T0, "run_id": "c", "subtask_id": "st-X", "event": "run_completed"},
    {"ts": _T1, "run_id": "c", "subtask_id": "st-X", "event": "verify_passed"},
]


# ── _extractDecisionPoints ─────────────────────────────────────────────────────

@pytest.mark.test_cli_features
class TestExtractDecisionPoints(unittest.TestCase):

    def test_empty_events_returns_empty(self):
        self.assertEqual(_extractDecisionPoints([]), [])

    def test_clean_trace_returns_empty(self):
        self.assertEqual(_extractDecisionPoints(_CLEAN), [])

    def test_mixed_trace_returns_four_decision_points(self):
        dps = _extractDecisionPoints(_MIXED)
        self.assertEqual(len(dps), 4)

    def test_required_keys_present_in_each_entry(self):
        dps = _extractDecisionPoints(_MIXED)
        for dp in dps:
            for key in ("index", "event", "subtask", "kind", "ts", "offset",
                        "fields", "context_before", "context_after"):
                with self.subTest(key=key, dp_event=dp["event"]):
                    self.assertIn(key, dp)

    def test_kinds_match_classify(self):
        dps = _extractDecisionPoints(_MIXED)
        kinds = {dp["kind"] for dp in dps}
        self.assertEqual(kinds, {"FAIL", "REPLAN", "CHALLENGE"})

    def test_first_decision_point_has_no_context_before(self):
        # First event in _MIXED is a divergence — nothing before it.
        dps = _extractDecisionPoints(_MIXED)
        self.assertEqual(dps[0]["context_before"], [])

    def test_first_decision_point_has_context_after(self):
        # First event (index 0): up to 2 events after it (indices 1 and 2).
        dps = _extractDecisionPoints(_MIXED)
        self.assertGreater(len(dps[0]["context_after"]), 0)
        self.assertLessEqual(len(dps[0]["context_after"]), 2)

    def test_context_window_respected(self):
        dps = _extractDecisionPoints(_MIXED, context_window=1)
        for dp in dps:
            self.assertLessEqual(len(dp["context_before"]), 1)
            self.assertLessEqual(len(dp["context_after"]), 1)

    def test_zero_context_window_returns_empty_context(self):
        dps = _extractDecisionPoints(_MIXED, context_window=0)
        for dp in dps:
            self.assertEqual(dp["context_before"], [])
            self.assertEqual(dp["context_after"], [])

    def test_index_field_is_position_in_events(self):
        dps = _extractDecisionPoints(_MIXED)
        # First divergence is at index 0 of _MIXED.
        self.assertEqual(dps[0]["index"], 0)
        # Second divergence is at index 1 of _MIXED.
        self.assertEqual(dps[1]["index"], 1)

    def test_context_entries_have_event_and_subtask(self):
        dps = _extractDecisionPoints(_MIXED)
        for dp in dps:
            for ctx in dp["context_before"] + dp["context_after"]:
                self.assertIn("event", ctx)
                self.assertIn("subtask", ctx)

    def test_offset_starts_with_t_plus(self):
        dps = _extractDecisionPoints(_MIXED)
        for dp in dps:
            self.assertTrue(dp["offset"].startswith("T+"), dp["offset"])

    def test_ts_field_is_float(self):
        dps = _extractDecisionPoints(_MIXED)
        for dp in dps:
            self.assertIsInstance(dp["ts"], float)

    def test_pass_events_excluded(self):
        events = [
            {"ts": _T0, "run_id": "p", "subtask_id": "s", "event": "run_completed"},
            {"ts": _T1, "run_id": "p", "subtask_id": "s", "event": "verify_passed"},
        ]
        self.assertEqual(_extractDecisionPoints(events), [])

    def test_info_events_excluded(self):
        events = [
            {"ts": _T0, "run_id": "i", "subtask_id": "s", "event": "subtask_started"},
            {"ts": _T1, "run_id": "i", "subtask_id": "s", "event": "executor_invoked"},
        ]
        self.assertEqual(_extractDecisionPoints(events), [])

    def test_single_divergence_in_middle_has_both_contexts(self):
        events = [
            {"ts": _T0, "run_id": "x", "subtask_id": "s", "event": "run_completed"},
            {"ts": _T1, "run_id": "x", "subtask_id": "s", "event": "verification_failed"},
            {"ts": _T2, "run_id": "x", "subtask_id": "s", "event": "verify_passed"},
        ]
        dps = _extractDecisionPoints(events)
        self.assertEqual(len(dps), 1)
        self.assertEqual(len(dps[0]["context_before"]), 1)
        self.assertEqual(len(dps[0]["context_after"]), 1)
        self.assertEqual(dps[0]["context_before"][0]["event"], "run_completed")
        self.assertEqual(dps[0]["context_after"][0]["event"], "verify_passed")

    def test_missing_ts_handled_gracefully(self):
        events = [{"run_id": "t", "subtask_id": "s", "event": "verification_failed"}]
        dps = _extractDecisionPoints(events)
        self.assertEqual(len(dps), 1)
        self.assertIsInstance(dps[0]["ts"], float)

    def test_none_subtask_id_becomes_dash(self):
        events = [{"ts": _T0, "run_id": "t", "subtask_id": None, "event": "replan_split"}]
        dps = _extractDecisionPoints(events)
        self.assertEqual(dps[0]["subtask"], "-")

    def test_multiple_context_window_default(self):
        # Default context_window=2; a middle divergence should have up to 2 entries each side.
        events = [
            {"ts": _T0, "run_id": "x", "subtask_id": "s", "event": "verify_passed"},
            {"ts": _T1, "run_id": "x", "subtask_id": "s", "event": "run_completed"},
            {"ts": _T2, "run_id": "x", "subtask_id": "s", "event": "verification_failed"},
            {"ts": _T3, "run_id": "x", "subtask_id": "s", "event": "verify_passed"},
            {"ts": _T4, "run_id": "x", "subtask_id": "s", "event": "run_completed"},
        ]
        dps = _extractDecisionPoints(events)
        self.assertEqual(len(dps), 1)
        self.assertEqual(len(dps[0]["context_before"]), 2)
        self.assertEqual(len(dps[0]["context_after"]), 2)

    def test_events_ordering_preserved_in_context(self):
        events = [
            {"ts": _T0, "run_id": "x", "subtask_id": "s", "event": "run_completed"},
            {"ts": _T1, "run_id": "x", "subtask_id": "s", "event": "verification_failed"},
            {"ts": _T2, "run_id": "x", "subtask_id": "s", "event": "replan_triggered"},
        ]
        dps = _extractDecisionPoints(events)
        # First dp at index 1 has "run_completed" in context_before.
        self.assertEqual(dps[0]["context_before"][0]["event"], "run_completed")
        # Second dp at index 2 has "verification_failed" in context_before.
        self.assertEqual(dps[1]["context_before"][-1]["event"], "verification_failed")


# ── buildStepSpec ─────────────────────────────────────────────────────────────

@pytest.mark.test_cli_features
class TestBuildStepSpecGDP(unittest.TestCase):

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
class TestGetDecisionPointsGDP(unittest.TestCase):

    @staticmethod
    def _event(event: str, subtask: str, second: int) -> dict:
        return {
            "ts": f"2026-01-01T00:00:{second:02d}+00:00",
            "run_id": "run-001",
            "subtask_id": subtask,
            "event": event,
        }

    def _run_gdp(self, run_id=None, recent=None, events=None) -> dict:
        """Helper: patch tracing, then call getDecisionPoints (replay is in-process)."""
        if recent is None:
            recent = []
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=recent):
            if events is None:
                return _wf.getDecisionPoints(run_id=run_id)
            with mock.patch.object(_wf.tracing, "readEvents", return_value=events):
                return _wf.getDecisionPoints(run_id=run_id)

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

    def test_divergences_surfaced_as_decision_points(self):
        events = [self._event("verification_failed", "st-A", 0),
                  self._event("verify_passed", "st-A", 1)]
        result = self._run_gdp(recent=["run-001"], events=events)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["decision_points"]), 1)
        self.assertEqual(result["decision_points"][0]["kind"], "FAIL")

    def test_total_events_propagated(self):
        events = [self._event("verify_passed", "st-A", i) for i in range(9)]
        result = self._run_gdp(recent=["run-001"], events=events)
        self.assertEqual(result["total_events"], 9)

    def test_read_error_ok_false(self):
        with mock.patch.object(_wf.tracing, "recentRunIds", return_value=["run-001"]):
            with mock.patch.object(_wf.tracing, "readEvents",
                                   side_effect=RuntimeError("crash")):
                result = _wf.getDecisionPoints()
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])

    def test_run_id_propagated(self):
        events = [self._event("verify_passed", "st-A", 0)]
        result = self._run_gdp(recent=["my-run"], events=events)
        self.assertEqual(result["run_id"], "my-run")

    def test_empty_divergences_gives_empty_decision_points(self):
        events = [self._event("verify_passed", "st-A", 0)]
        result = self._run_gdp(recent=["run-001"], events=events)
        self.assertTrue(result["ok"])
        self.assertEqual(result["decision_points"], [])
