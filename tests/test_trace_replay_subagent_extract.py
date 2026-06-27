"""Tests for _extractDecisionPoints in agents/trace-replay.py (CLI module).

Covers the step-by-step context-window extractor used for multi-step
workflow debugging.

CWD-independent design: all module discovery uses Path(__file__).resolve().

Split from test_trace_replay_subagent.py (was 408 lines).
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Load trace-replay.py CLI module (hyphenated filename requires spec loader).
_cli_spec = importlib.util.spec_from_file_location(
    "trace_replay_cli", _ROOT / "agents" / "trace-replay.py"
)
_cli = importlib.util.module_from_spec(_cli_spec)
_cli_spec.loader.exec_module(_cli)

_extractDecisionPoints = _cli._extractDecisionPoints


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


if __name__ == "__main__":
    _loader = unittest.TestLoader()
    _suite = unittest.TestSuite([
        _loader.loadTestsFromTestCase(TestExtractDecisionPoints),
    ])
    _result = unittest.TextTestRunner(verbosity=2).run(_suite)
    sys.exit(0 if _result.wasSuccessful() else 1)
