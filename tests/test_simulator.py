"""Unit tests for simulation.py error handling.

Integration-level and happy-path unit tests live in test_dry_run.py,
test_builder_sim.py, and test_simulation_units.py; this file focuses on the
failure / edge-case seams.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from platform_core.simulator.simulation import (
    BuilderBrain,
    SimBrain,
    SimObs,
    builderRunClaude,
    simRunClaude,
)


# ---------------------------------------------------------------------------
# SimBrain: non-dict message items (robustness)
# ---------------------------------------------------------------------------

class TestSimBrainNonDictMessages(unittest.TestCase):
    def test_non_dict_message_items_do_not_crash(self):
        brain = SimBrain()
        resp = brain.chat(messages=["string item", 42, None])
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)

    def test_none_messages_does_not_crash(self):
        brain = SimBrain()
        resp = brain.chat(messages=None)
        self.assertIn("message", resp)

    def test_invocation_spec_via_mixed_messages(self):
        brain = SimBrain(n_subtasks=2)
        msgs = ["bad", {"role": "user", "content": "invocation spec please"}]
        resp = brain.chat(messages=msgs)
        data = json.loads(resp["message"]["content"])
        self.assertIn("prompt", data)


# ---------------------------------------------------------------------------
# BuilderBrain: non-dict message items (robustness)
# ---------------------------------------------------------------------------

class TestBuilderBrainNonDictMessages(unittest.TestCase):
    def test_non_dict_items_do_not_crash(self):
        brain = BuilderBrain("/tmp/w", n_subtasks=1)
        resp = brain.chat(messages=["garbage", 999])
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)

    def test_none_messages_returns_plan(self):
        brain = BuilderBrain("/tmp/w", n_subtasks=2)
        resp = brain.chat(messages=None)
        data = json.loads(resp["message"]["content"])
        self.assertIn("subtasks", data)


# ---------------------------------------------------------------------------
# builderRunClaude: write-failure handling
# ---------------------------------------------------------------------------

class TestBuilderRunClaudeWriteFailure(unittest.TestCase):
    def test_unwritable_path_returns_error_dict_not_exception(self):
        subtask = {
            "subtask_id": "st-fail",
            "verify": {"cmd": 'python "/no_such_dir/\x00/f.py"', "expect": "exit_zero"},
        }
        result = builderRunClaude({}, subtask=subtask)
        self.assertIsInstance(result, dict)
        self.assertFalse(result["ok"])
        self.assertTrue(result["is_error"])
        self.assertIn("write failed", result["stdout"])
        self.assertEqual(result["returncode"], 1)
        self.assertIsNone(result["session_id"])

    def test_result_has_all_required_keys(self):
        subtask = {
            "subtask_id": "st-x",
            "verify": {"cmd": 'python "/no_such_dir/\x00/f.py"', "expect": "exit_zero"},
        }
        result = builderRunClaude({}, subtask=subtask)
        for key in ("ok", "returncode", "stdout", "is_error", "session_id"):
            self.assertIn(key, result)

    def test_success_path_still_works(self):
        with tempfile.TemporaryDirectory() as d:
            target = str(Path(d) / "feature_1.py")
            subtask = {"subtask_id": "st-ok",
                       "verify": {"cmd": f'python "{target}"', "expect": "exit_zero"}}
            result = builderRunClaude({}, subtask=subtask, work_dir=d)
            self.assertTrue(result["ok"])
            self.assertFalse(result["is_error"])


# ---------------------------------------------------------------------------
# SimObs edge cases
# ---------------------------------------------------------------------------

class TestSimObsEdgeCases(unittest.TestCase):
    def test_write_note_with_empty_content(self):
        obs = SimObs()
        rv = obs.writeNote("a.md", "")
        self.assertTrue(rv["ok"])
        self.assertEqual(obs.notes["a.md"], "")

    def test_append_note_with_empty_content(self):
        obs = SimObs()
        obs.writeNote("a.md", "base")
        obs.appendNote("a.md", "")
        self.assertEqual(obs.notes["a.md"], "base")

    def test_write_then_read_roundtrip(self):
        obs = SimObs()
        obs.writeNote("x.md", "roundtrip content")
        self.assertEqual(obs.readNote("x.md"), "roundtrip content")

    def test_multiple_independent_keys(self):
        obs = SimObs()
        obs.writeNote("a.md", "aaa")
        obs.writeNote("b.md", "bbb")
        self.assertEqual(obs.readNote("a.md"), "aaa")
        self.assertEqual(obs.readNote("b.md"), "bbb")


# ---------------------------------------------------------------------------
# simRunClaude edge cases
# ---------------------------------------------------------------------------

class TestSimRunClaudeEdgeCases(unittest.TestCase):
    def test_spec_as_none_does_not_crash(self):
        result = simRunClaude(None)
        self.assertIsInstance(result, dict)
        self.assertTrue(result["ok"])

    def test_spec_as_empty_dict(self):
        result = simRunClaude({})
        self.assertTrue(result["ok"])
        self.assertEqual(result["returncode"], 0)

    def test_subtask_without_subtask_id_key(self):
        result = simRunClaude({}, subtask={})
        self.assertIn("?", result["stdout"])

    def test_all_envelope_keys_present(self):
        result = simRunClaude({})
        for key in ("ok", "returncode", "stdout", "is_error", "session_id"):
            self.assertIn(key, result)
