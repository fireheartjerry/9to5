"""Chaos-simulation mode: a --dry-run variant whose doubles inject the SAME fault
shapes the executor/brain fuzz tests use (None, non-dict, {}, partial, mistyped,
is_error envelope, simulated-timeout marker + malformed/empty brain completions),
deterministically seeded. The invariant: a full run under chaos ALWAYS reaches a
graceful terminal status and NEVER raises out of runFull.

Kept fast (20 seeds, chaos brain half-valid) and the filename carries no slow-lane
substring so it runs in the fast lane.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import orchestrator as O
from state.task import TaskState

import platform_core.simulator.chaos as chaos

_GRACEFUL_TERMINAL = {"done", "complete", "partial", "failed", "aborted"}


class TestChaosSim(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "tasks").mkdir()
        (self.dir / "control").mkdir()
        self.work = self.dir / "work"
        self.work.mkdir()
        self._patches = [
            mock.patch.object(config, "STATE_DIR", self.dir / "tasks"),
            mock.patch.object(config, "CONTROL_DIR", self.dir / "control"),
            mock.patch.object(config, "WEB_DASHBOARD", False),
            mock.patch.object(config, "DISCORD_DASHBOARD", False),
            mock.patch.object(O, "refreshClaudeKnowledge", lambda *a, **k: ""),
            mock.patch.object(O, "startWebDashboard", lambda *a, **k: None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_chaos_seeds_reach_graceful_terminal(self):
        bad = []
        for seed in range(20):
            st = TaskState.create("build (1) a (2) b (3) c", 1.0)
            st.setElaboratedGoal(st.meta["goal_raw"])
            st.save()
            orch = chaos.buildChaosOrchestrator(str(self.work), seed)
            try:
                summary = orch.runFull(st, work_dir=str(self.work), auto_pr=False,
                                       control_mode="watch")
                if summary["status"] not in _GRACEFUL_TERMINAL:
                    bad.append((seed, summary["status"], summary.get("reason")))
            except Exception as e:  # noqa: BLE001 -- a raised exception is the worst outcome
                bad.append((seed, "RAISED", repr(e)))
        self.assertEqual(bad, [], f"chaos sim produced bad outcomes: {bad[:8]}")

    def test_chaos_run_claude_is_deterministic(self):
        a = chaos.chaosRunClaude(7)
        b = chaos.chaosRunClaude(7)
        seq_a = [_normalizeShape(a({}, subtask={"subtask_id": f"st-{i}"})) for i in range(30)]
        seq_b = [_normalizeShape(b({}, subtask={"subtask_id": f"st-{i}"})) for i in range(30)]
        self.assertEqual(seq_a, seq_b)


def _normalizeShape(result):
    """Collapse a chaos result into a comparable tag (dicts carry a fresh sid string)."""
    if result is None:
        return "none"
    if not isinstance(result, dict):
        return f"scalar:{type(result).__name__}"
    return "dict:" + ",".join(sorted(result.keys()))

