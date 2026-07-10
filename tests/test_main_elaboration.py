"""Launch-flow regression tests for elaboration approval and scope synchronization."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import main


class _State:
    def __init__(self):
        self.meta = {"goal_raw": "improve reliability"}
        self.elaborated = ""
        self.universe = {}
        self.saved = 0

    def setElaboratedGoal(self, value):
        self.elaborated = value

    def setUniverse(self, value):
        self.universe = value

    def setStatus(self, _status):
        pass

    def save(self):
        self.saved += 1


class TestElaborationApproval(unittest.TestCase):
    def test_human_edit_regenerates_universe_from_edited_spec(self):
        state = _State()
        state.meta["elaboration"] = {"human_edited": False}
        args = SimpleNamespace(auto_approve=False)
        regenerated = {"allowed_paths": ["agents/planning"], "hard_boundaries": [".git"]}
        with mock.patch("builtins.input", return_value="edit"), \
             mock.patch.object(main, "_collectEditedSpec", return_value="# Objective\nEdited"), \
             mock.patch.object(main.elaborator, "extractUniverse", return_value=regenerated) as extract:
            self.assertTrue(main._handleApproval(args, state, "C:/repo"))
        extract.assert_called_once_with("improve reliability", "# Objective\nEdited", "C:/repo")
        self.assertEqual(state.elaborated, "# Objective\nEdited")
        self.assertEqual(state.universe, regenerated)
        self.assertTrue(state.meta["elaboration_human_edited"])
        self.assertTrue(state.meta["elaboration"]["human_edited"])


class TestDryRunContract(unittest.TestCase):
    def test_dry_run_never_waits_for_gated_approval(self):
        captured = {}

        class State:
            def setElaboratedGoal(self, _value):
                pass

            def setUniverse(self, _value):
                pass

            def save(self):
                pass

        class Orchestrator:
            def runFull(self, *args, **kwargs):
                captured.update(kwargs)
                return {"status": "done"}

        args = SimpleNamespace(goal="offline smoke", hours=1.0, chaos=None,
                               mode="gated", parallel=1)
        flags = SimpleNamespace(WEB_DASHBOARD=True, CLAUDE_DOC_FETCH=True)
        with mock.patch.object(main.app_settings, "runFlags", return_value=flags), \
             mock.patch.object(main.config, "ensureDirs"), \
             mock.patch.object(main.TaskState, "create", return_value=State()), \
             mock.patch.object(main, "_applyWorkProfile"), \
             mock.patch("platform_core.simulator.simulation.buildOrchestrator", return_value=Orchestrator()) as build, \
             mock.patch("tempfile.mkdtemp", return_value="C:/dry-run"):
            self.assertEqual(main._runDryRun(args), 0)
        self.assertEqual(captured["control_mode"], "watch")
        build.assert_called_once_with(offline=True)
