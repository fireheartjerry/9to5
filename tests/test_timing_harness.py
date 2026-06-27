"""tests/test_timing_harness.py -- Acceptance test for the timing harness.

Usage:
  python tests/test_timing_harness.py --workflow workflows/definitions/bug_investigation.json

Exit 0: harness ran, ratio <= SPEEDUP_THRESHOLD (>=20% speedup verified), JSON updated.
Exit 1: harness failed or speedup threshold not met.
"""
from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from agents.timing_harness import (  # noqa: E402
    SPEEDUP_THRESHOLD,
    TimingResult,
    measureWorkflow,
    updateSpeedupRatio,
)


def _resolveWorkflowPath(raw: str) -> Path:
    p = Path(raw)
    if p.is_absolute() and p.exists():
        return p
    candidate = _REPO_ROOT / p
    if candidate.exists():
        return candidate
    return p


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestTimingHarness(unittest.TestCase):
    def _simpleWorkflow(self) -> dict:
        return {
            "name": "test",
            "phases": [
                {"title": "P1", "parallel": True, "agents": [{"label": "a"}, {"label": "b"}]},
                {"title": "P2", "parallel": True, "agents": [{"label": "c"}, {"label": "d"}]},
            ],
        }

    def test_returns_timing_result(self):
        result = measureWorkflow(self._simpleWorkflow(), agent_duration=0.01)
        self.assertIsInstance(result, TimingResult)

    def test_concurrent_faster_than_sequential(self):
        result = measureWorkflow(self._simpleWorkflow(), agent_duration=0.03)
        self.assertLess(result.concurrent_secs, result.sequential_secs)

    def test_ratio_between_zero_and_one(self):
        result = measureWorkflow(self._simpleWorkflow(), agent_duration=0.02)
        self.assertGreater(result.ratio, 0.0)
        self.assertLess(result.ratio, 1.0)

    def test_meets_threshold_flag_consistent(self):
        result = measureWorkflow(self._simpleWorkflow(), agent_duration=0.02)
        self.assertEqual(result.meets_threshold, result.ratio <= SPEEDUP_THRESHOLD)

    def test_phase_and_agent_counts(self):
        result = measureWorkflow(self._simpleWorkflow(), agent_duration=0.01)
        self.assertEqual(result.phase_count, 2)
        self.assertEqual(result.agent_count, 4)

    def test_single_agent_phase_no_crash(self):
        wf = {
            "name": "single",
            "phases": [{"title": "P1", "parallel": False, "agents": [{"label": "a"}]}],
        }
        result = measureWorkflow(wf, agent_duration=0.01)
        self.assertEqual(result.agent_count, 1)
        self.assertIsInstance(result, TimingResult)

    def test_empty_phases_no_crash(self):
        result = measureWorkflow({"name": "empty", "phases": []}, agent_duration=0.01)
        self.assertEqual(result.agent_count, 0)
        self.assertEqual(result.phase_count, 0)

    def test_update_speedup_ratio_writes_json(self):
        import tempfile
        wf = {
            "name": "t",
            "phases": [{"title": "P1", "agents": [{"label": "a"}, {"label": "b"}]}],
            "speedup_model": {"estimated_wall_clock_ratio": 0.99},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(wf, f)
            tmp_path = Path(f.name)
        try:
            result = measureWorkflow(wf, agent_duration=0.02)
            updateSpeedupRatio(tmp_path, result)
            updated = json.loads(tmp_path.read_text(encoding="utf-8"))
            self.assertEqual(
                updated["speedup_model"]["estimated_wall_clock_ratio"],
                round(result.ratio, 4),
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_three_phase_workflow_meets_threshold(self):
        wf = {
            "name": "three_phase",
            "phases": [
                {"title": "A", "parallel": True, "agents": [{"label": "a1"}, {"label": "a2"}]},
                {"title": "B", "parallel": True, "agents": [{"label": "b1"}, {"label": "b2"}]},
                {"title": "C", "parallel": True, "agents": [{"label": "c1"}, {"label": "c2"}]},
            ],
        }
        result = measureWorkflow(wf, agent_duration=0.03)
        self.assertTrue(result.meets_threshold,
                        f"ratio {result.ratio:.4f} exceeds threshold {SPEEDUP_THRESHOLD}")


# ---------------------------------------------------------------------------
# Acceptance runner
# ---------------------------------------------------------------------------

def runWorkflowAcceptance(workflow_path: Path) -> bool:
    """Run timing harness on *workflow_path*. Returns True on pass."""
    if not workflow_path.exists():
        print(f"ERROR: workflow file not found: {workflow_path}", file=sys.stderr)
        return False

    data = json.loads(workflow_path.read_text(encoding="utf-8"))
    print(f"Workflow: {data.get('name', workflow_path.stem)}")
    print(f"  phases:  {len(data.get('phases', []))}")

    result = measureWorkflow(data)
    print(f"  sequential:  {result.sequential_secs:.4f}s")
    print(f"  concurrent:  {result.concurrent_secs:.4f}s")
    print(f"  ratio:       {result.ratio:.4f}  (threshold <= {SPEEDUP_THRESHOLD})")
    print(f"  agents:      {result.agent_count}")

    if not result.meets_threshold:
        print(
            f"FAIL: ratio {result.ratio:.4f} exceeds threshold {SPEEDUP_THRESHOLD}",
            file=sys.stderr,
        )
        return False

    updateSpeedupRatio(workflow_path, result)
    print(f"  updated speedup_model.estimated_wall_clock_ratio = {round(result.ratio, 4)}")
    print("PASS")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Timing harness acceptance test")
    parser.add_argument("--workflow", help="Path to workflow JSON (relative to repo root or absolute)")
    args, remaining = parser.parse_known_args()

    if args.workflow:
        workflow_path = _resolveWorkflowPath(args.workflow)
        acceptance_ok = runWorkflowAcceptance(workflow_path)

        # Also run unit tests
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromTestCase(TestTimingHarness)
        runner = unittest.TextTestRunner(verbosity=2)
        unit_result = runner.run(suite)

        sys.exit(0 if (acceptance_ok and unit_result.wasSuccessful()) else 1)
    else:
        unittest.main(argv=[sys.argv[0]] + remaining)
