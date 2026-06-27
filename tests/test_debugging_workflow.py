"""Tests for agents/debugging_workflow.py — integrated skill-gap + trace-replay workflow."""
import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.debugging_workflow import buildReport, run, _DEBUG_DOMAINS  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_gap_row(domain: str, demand: int, gap_score: float, covered_by: list) -> dict:
    return {
        "domain": domain,
        "demand": demand,
        "gap_score": gap_score,
        "covered_by": covered_by,
        "coverage_fraction": 0.0 if not covered_by else 0.5,
    }


def _make_trace_result(divergence_count: int = 0, ok: bool = True, error=None) -> dict:
    return {
        "ok": ok,
        "run_id": "run-test-001",
        "divergence_count": divergence_count,
        "high_activity_count": 0,
        "parallel_moments": 0,
        "total_events": 10,
        "divergences": [{"step": i} for i in range(divergence_count)],
        "raw": "{}",
        "error": error,
    }


# ---------------------------------------------------------------------------
# buildReport
# ---------------------------------------------------------------------------
class TestBuildReport(unittest.TestCase):

    def test_returns_required_keys(self):
        rows = [_make_gap_row("debugging", 50, 25.0, [])]
        trace = _make_trace_result()
        report = buildReport(rows, trace, {"debugging": set()})
        for key in ("ok", "gap_rows", "trace_result", "high_gap_domains",
                    "correlated", "recommendations", "inventory_count", "task_count"):
            self.assertIn(key, report)

    def test_ok_is_true(self):
        report = buildReport([], _make_trace_result(), {})
        self.assertTrue(report["ok"])

    def test_high_gap_domains_sorted_by_gap_desc(self):
        rows = [
            _make_gap_row("debugging", 80, 40.0, []),
            _make_gap_row("workflow", 60, 60.0, []),
            _make_gap_row("deployment", 30, 10.0, []),
        ]
        report = buildReport(rows, _make_trace_result(), {})
        self.assertEqual(report["high_gap_domains"], ["workflow", "debugging", "deployment"])

    def test_no_divergences_yields_no_correlated(self):
        rows = [_make_gap_row("debugging", 100, 50.0, [])]
        report = buildReport(rows, _make_trace_result(divergence_count=0), {})
        self.assertEqual(report["correlated"], [])

    def test_divergences_correlate_debug_domains_only(self):
        rows = [
            _make_gap_row("debugging", 100, 50.0, []),
            _make_gap_row("deployment", 80, 40.0, []),
        ]
        report = buildReport(rows, _make_trace_result(divergence_count=3), {})
        correlated_domains = [c["domain"] for c in report["correlated"]]
        self.assertIn("debugging", correlated_domains)
        self.assertNotIn("deployment", correlated_domains)

    def test_correlated_entry_has_divergence_count(self):
        rows = [_make_gap_row("debugging", 100, 50.0, [])]
        report = buildReport(rows, _make_trace_result(divergence_count=7), {})
        self.assertEqual(report["correlated"][0]["divergence_count"], 7)

    def test_recommendation_create_when_no_coverage(self):
        rows = [_make_gap_row("debugging", 100, 50.0, covered_by=[])]
        report = buildReport(rows, _make_trace_result(divergence_count=1), {})
        recs = " ".join(report["recommendations"])
        self.assertIn("Create new skill", recs)
        self.assertIn("debugging", recs)

    def test_recommendation_strengthen_when_partial_coverage(self):
        rows = [_make_gap_row("debugging", 100, 25.0, covered_by=["debugging"])]
        report = buildReport(rows, _make_trace_result(divergence_count=2), {})
        recs = " ".join(report["recommendations"])
        self.assertIn("Strengthen", recs)
        self.assertIn("debugging", recs)

    def test_non_debug_gap_always_recommended(self):
        rows = [
            _make_gap_row("debugging", 100, 50.0, []),
            _make_gap_row("deployment", 80, 40.0, []),
        ]
        # No divergences — only non-debug proactive recommendation fires.
        report = buildReport(rows, _make_trace_result(divergence_count=0), {})
        recs = " ".join(report["recommendations"])
        self.assertIn("deployment", recs)
        self.assertIn("proactively", recs)

    def test_zero_gap_rows_excluded_from_high_gap(self):
        rows = [
            _make_gap_row("debugging", 50, 0.0, ["debugging"]),
            _make_gap_row("deployment", 30, 15.0, []),
        ]
        report = buildReport(rows, _make_trace_result(), {})
        self.assertNotIn("debugging", report["high_gap_domains"])
        self.assertIn("deployment", report["high_gap_domains"])

    def test_inventory_count_reflects_inventory_size(self):
        inventory = {"a": set(), "b": set(), "c": set()}
        report = buildReport([], _make_trace_result(), inventory)
        self.assertEqual(report["inventory_count"], 3)

    def test_empty_inputs_no_crash(self):
        report = buildReport([], _make_trace_result(), {})
        self.assertTrue(report["ok"])
        self.assertEqual(report["recommendations"], [])
        self.assertEqual(report["correlated"], [])


# ---------------------------------------------------------------------------
# run() — mocked integration
# ---------------------------------------------------------------------------
class TestRun(unittest.TestCase):

    def _mock_sga(self, inventory: dict, gap_rows: list, tasks: list):
        """Return a context manager that patches the three SGA functions in the module."""
        demand = Counter({r["domain"]: r["demand"] for r in gap_rows})
        return mock.patch.multiple(
            "agents.debugging_workflow",
            loadSkillInventory=mock.Mock(return_value=inventory),
            loadTaskHistory=mock.Mock(return_value=tasks),
            buildDemandCounter=mock.Mock(return_value=demand),
            scoreDomains=mock.Mock(return_value=gap_rows),
        )

    def test_run_returns_expected_keys(self):
        gap_rows = [_make_gap_row("debugging", 50, 25.0, [])]
        with self._mock_sga({"debugging": set()}, gap_rows, [{"id": "t1"}]):
            with mock.patch("agents.debugging_workflow._runTraceReplay",
                            return_value=_make_trace_result(divergence_count=0)):
                result = run()
        for key in ("ok", "gap_rows", "trace_result", "high_gap_domains",
                    "correlated", "recommendations", "inventory_count",
                    "task_count", "error"):
            self.assertIn(key, result)

    def test_run_task_count_set(self):
        gap_rows = [_make_gap_row("deployment", 40, 20.0, [])]
        tasks = [{"id": f"t{i}"} for i in range(5)]
        with self._mock_sga({"deployment": set()}, gap_rows, tasks):
            with mock.patch("agents.debugging_workflow._runTraceReplay",
                            return_value=_make_trace_result()):
                result = run()
        self.assertEqual(result["task_count"], 5)

    def test_run_error_forwarded_from_trace(self):
        gap_rows = []
        with self._mock_sga({}, gap_rows, []):
            with mock.patch("agents.debugging_workflow._runTraceReplay",
                            return_value=_make_trace_result(error="no_traces")):
                result = run()
        self.assertEqual(result["error"], "no_traces")

    def test_run_no_trace_still_returns_ok(self):
        gap_rows = [_make_gap_row("workflow", 30, 15.0, [])]
        with self._mock_sga({"workflow": set()}, gap_rows, []):
            with mock.patch("agents.debugging_workflow._runTraceReplay",
                            return_value=_make_trace_result(divergence_count=0, error="no_traces")):
                result = run()
        self.assertTrue(result["ok"])

    def test_run_correlated_when_trace_has_divergences(self):
        gap_rows = [_make_gap_row("debugging", 100, 50.0, [])]
        with self._mock_sga({"debugging": set()}, gap_rows, []):
            with mock.patch("agents.debugging_workflow._runTraceReplay",
                            return_value=_make_trace_result(divergence_count=4)):
                result = run()
        self.assertGreater(len(result["correlated"]), 0)
        self.assertEqual(result["correlated"][0]["domain"], "debugging")

    def test_run_passes_run_id_to_trace(self):
        gap_rows = []
        with self._mock_sga({}, gap_rows, []):
            mock_trace = mock.Mock(return_value=_make_trace_result())
            with mock.patch("agents.debugging_workflow._runTraceReplay", mock_trace):
                run(run_id="run-xyz", limit=3, calibrate_limit=10)
        mock_trace.assert_called_once_with(run_id="run-xyz", limit=3, calibrate_limit=10)


# ---------------------------------------------------------------------------
# _DEBUG_DOMAINS constant
# ---------------------------------------------------------------------------
class TestDebugDomains(unittest.TestCase):
    def test_debugging_in_debug_domains(self):
        self.assertIn("debugging", _DEBUG_DOMAINS)

    def test_deployment_not_in_debug_domains(self):
        self.assertNotIn("deployment", _DEBUG_DOMAINS)


if __name__ == "__main__":
    unittest.main()
