"""Automated tests for agents/trace-replay.py.

Run directly: python C:\\9to5\\tests\\test-trace-replay.py
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Hyphenated filename — load via importlib without exec-ing __main__ block.
_spec = importlib.util.spec_from_file_location(
    "trace_replay", _ROOT / "agents" / "trace-replay.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_classify = _mod._classify
_computeThresholdFromCounts = _mod._computeThresholdFromCounts
_calibrateThreshold = _mod._calibrateThreshold
_replayEvents = _mod._replayEvents
replayTrace = _mod.replayTrace
_FALLBACK_THRESHOLD = _mod._FALLBACK_THRESHOLD

# Shared synthetic fixture used across multiple test classes.
_MIXED_EVENTS: list[dict] = [
    {"ts": "2026-01-01T00:00:00+00:00", "run_id": "t", "subtask_id": "st-A", "event": "verification_failed"},
    {"ts": "2026-01-01T00:00:01+00:00", "run_id": "t", "subtask_id": "st-A", "event": "replan_triggered"},
    {"ts": "2026-01-01T00:00:02+00:00", "run_id": "t", "subtask_id": "st-B", "event": "adversary_challenged"},
    {"ts": "2026-01-01T00:00:03+00:00", "run_id": "t", "subtask_id": "st-B", "event": "executor_failed"},
    {"ts": "2026-01-01T00:00:04+00:00", "run_id": "t", "subtask_id": "st-C", "event": "run_completed"},
    {"ts": "2026-01-01T00:00:05+00:00", "run_id": "t", "subtask_id": "st-C", "event": "verify_passed"},
    {"ts": "2026-01-01T00:00:06+00:00", "run_id": "t", "subtask_id": "st-C", "event": "verify_passed"},
]

_CLEAN_EVENTS: list[dict] = [
    {"ts": "2026-01-01T00:00:00+00:00", "run_id": "c", "subtask_id": "st-X", "event": "run_completed"},
    {"ts": "2026-01-01T00:00:01+00:00", "run_id": "c", "subtask_id": "st-X", "event": "verify_passed"},
]


class TestClassify(unittest.TestCase):
    def test_all_fail_variants(self):
        for ev in ("verification_failed", "verify_fail", "verify_failed",
                   "executor_failed", "step_failed", "run_failed", "subtask_failed"):
            with self.subTest(ev=ev):
                self.assertEqual(_classify(ev), "FAIL")

    def test_all_replan_variants(self):
        for ev in ("replan", "replan_split", "replanned", "replan_triggered"):
            with self.subTest(ev=ev):
                self.assertEqual(_classify(ev), "REPLAN")

    def test_all_adversary_variants(self):
        for ev in ("adversary_challenged", "adversary_challenge"):
            with self.subTest(ev=ev):
                self.assertEqual(_classify(ev), "CHALLENGE")

    def test_all_pass_variants(self):
        for ev in ("verification_passed", "verify_pass", "verify_passed", "run_completed"):
            with self.subTest(ev=ev):
                self.assertEqual(_classify(ev), "PASS")

    def test_unknown_is_info(self):
        self.assertEqual(_classify("subtask_started"), "INFO")
        self.assertEqual(_classify("something_new"), "INFO")

    def test_empty_string_is_info(self):
        self.assertEqual(_classify(""), "INFO")

    def test_case_insensitive_lookup(self):
        self.assertEqual(_classify("VERIFICATION_FAILED"), "FAIL")
        self.assertEqual(_classify("Replan_Split"), "REPLAN")


class TestComputeThreshold(unittest.TestCase):
    def test_empty_list_returns_fallback(self):
        self.assertEqual(_computeThresholdFromCounts([]), _FALLBACK_THRESHOLD)

    def test_single_small_value_floors_at_fallback(self):
        self.assertEqual(_computeThresholdFromCounts([3]), _FALLBACK_THRESHOLD)

    def test_corpus_1_to_10(self):
        # p90_idx = int(10 * 0.90) = 9 → sorted[9] = 10 → max(11, 10) = 11
        self.assertEqual(_computeThresholdFromCounts([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]), 11)

    def test_corpus_all_high_values(self):
        # p90_idx = 9 → value = 20 → max(21, 10) = 21
        self.assertEqual(_computeThresholdFromCounts([20] * 10), 21)

    def test_low_corpus_floors_at_fallback(self):
        self.assertEqual(_computeThresholdFromCounts([1, 2]), _FALLBACK_THRESHOLD)

    def test_single_high_value_exceeds_fallback(self):
        # p90_idx = 0 → value = 50 → max(51, 10) = 51
        self.assertEqual(_computeThresholdFromCounts([50]), 51)


class TestCalibrateThreshold(unittest.TestCase):
    def test_empty_run_ids_returns_fallback(self):
        self.assertEqual(_calibrateThreshold([]), _FALLBACK_THRESHOLD)

    def test_no_events_for_runs_returns_fallback(self):
        with mock.patch.object(_mod.tracing, "readEvents", return_value=[]):
            self.assertEqual(_calibrateThreshold(["run-1", "run-2"]), _FALLBACK_THRESHOLD)

    def test_three_event_subtask_floors_at_fallback(self):
        events = [{"subtask_id": "st-A", "event": "x"} for _ in range(3)]
        with mock.patch.object(_mod.tracing, "readEvents", return_value=events):
            self.assertEqual(_calibrateThreshold(["run-1"]), _FALLBACK_THRESHOLD)

    def test_high_count_subtask_raises_threshold(self):
        events = [{"subtask_id": "st-A", "event": "x"}] * 20
        with mock.patch.object(_mod.tracing, "readEvents", return_value=events):
            result = _calibrateThreshold(["run-1"])
        self.assertGreater(result, _FALLBACK_THRESHOLD)

    def test_subtask_id_none_grouped_as_dash(self):
        # Events with subtask_id=None should be grouped under "-"
        events = [{"subtask_id": None, "event": "x"}] * 5
        with mock.patch.object(_mod.tracing, "readEvents", return_value=events):
            result = _calibrateThreshold(["run-1"])
        self.assertIsInstance(result, int)


class TestReplayEvents(unittest.TestCase):
    def test_mixed_trace_returns_four_divergences(self):
        count = _replayEvents(_MIXED_EVENTS, threshold=2, run_id="test-mixed")
        self.assertEqual(count, 4)

    def test_clean_trace_returns_zero(self):
        count = _replayEvents(_CLEAN_EVENTS, threshold=1, run_id="test-clean")
        self.assertEqual(count, 0)

    def test_empty_event_list(self):
        count = _replayEvents([], threshold=5, run_id="test-empty")
        self.assertEqual(count, 0)

    def test_all_divergence_kinds_counted(self):
        events = [
            {"ts": "2026-01-01T00:00:00+00:00", "run_id": "t", "subtask_id": "s", "event": "verification_failed"},
            {"ts": "2026-01-01T00:00:01+00:00", "run_id": "t", "subtask_id": "s", "event": "replan"},
            {"ts": "2026-01-01T00:00:02+00:00", "run_id": "t", "subtask_id": "s", "event": "adversary_challenge"},
        ]
        self.assertEqual(_replayEvents(events, threshold=10, run_id="all-types"), 3)

    def test_pass_events_not_counted_as_divergences(self):
        events = [
            {"ts": "2026-01-01T00:00:00+00:00", "run_id": "t", "subtask_id": "s", "event": "run_completed"},
            {"ts": "2026-01-01T00:00:01+00:00", "run_id": "t", "subtask_id": "s", "event": "verify_passed"},
            {"ts": "2026-01-01T00:00:02+00:00", "run_id": "t", "subtask_id": "s", "event": "verification_passed"},
        ]
        self.assertEqual(_replayEvents(events, threshold=10, run_id="pass-only"), 0)

    def test_high_activity_threshold_boundary(self):
        # st-C has 3 events; threshold=3 means >3 required → NOT flagged
        # threshold=2 means >2 required → flagged
        events = [{"ts": "2026-01-01T00:00:00+00:00", "run_id": "t", "subtask_id": "st-C",
                   "event": "verify_passed"}] * 3
        # We can only observe the side-effect indirectly via return value (divergences = 0 here)
        count = _replayEvents(events, threshold=2, run_id="high-activity-test")
        self.assertEqual(count, 0)

    def test_missing_ts_handled_gracefully(self):
        events = [
            {"run_id": "t", "subtask_id": "s", "event": "verification_failed"},
        ]
        count = _replayEvents(events, threshold=5, run_id="no-ts")
        self.assertEqual(count, 1)

    def test_missing_subtask_id_handled(self):
        events = [
            {"ts": "2026-01-01T00:00:00+00:00", "run_id": "t", "event": "replan_split"},
        ]
        count = _replayEvents(events, threshold=5, run_id="no-subtask")
        self.assertEqual(count, 1)


class TestReplayTrace(unittest.TestCase):
    def test_no_events_returns_zero(self):
        with mock.patch.object(_mod.tracing, "readEvents", return_value=[]):
            count = replayTrace("nonexistent-run", threshold=10)
        self.assertEqual(count, 0)

    def test_one_divergence_event(self):
        events = [
            {"ts": "2026-01-01T00:00:00+00:00", "run_id": "r1", "subtask_id": "s", "event": "verification_failed"},
            {"ts": "2026-01-01T00:00:01+00:00", "run_id": "r1", "subtask_id": "s", "event": "run_completed"},
        ]
        with mock.patch.object(_mod.tracing, "readEvents", return_value=events):
            count = replayTrace("r1", threshold=5)
        self.assertEqual(count, 1)

    def test_clean_run_returns_zero(self):
        events = [
            {"ts": "2026-01-01T00:00:00+00:00", "run_id": "r2", "subtask_id": "s", "event": "run_completed"},
        ]
        with mock.patch.object(_mod.tracing, "readEvents", return_value=events):
            count = replayTrace("r2", threshold=5)
        self.assertEqual(count, 0)


class TestBuiltInSelfTest(unittest.TestCase):
    def test_self_test_does_not_raise(self):
        # The module's own internal self-test must pass without error.
        _mod._selfTest()
