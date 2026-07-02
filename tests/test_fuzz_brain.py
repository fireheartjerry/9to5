"""Property-based fuzz of the Ollama brain outputs.

INVARIANT: with an executor that always succeeds, a run must ALWAYS finish 'done'
no matter what garbage the brain emits -- the local 7B model produces malformed,
mistyped, oversized, and partial JSON constantly, and none of it may crash the core
loop (status 'blocked') or fail/hang the run. Seeded for reproducibility.
"""
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import orchestrator as O
import platform_core.simulator.simulation as simulation
from orchestrator import Orchestrator
from state.task import TaskState

# A zoo of malformed brain payloads (the value of resp["message"]["content"], or the
# whole resp shape) that a 7B model realistically produces.
_GARBAGE_CONTENT = [
    None, "", "   ", "not json at all", "{", "}{", "[1,2,3]", "42", "null", "true",
    '{"subtasks": 5}', '{"subtasks": "nope"}', '{"subtasks": [1, 2, 3]}',
    '{"subtasks": [{"title": 5}]}', '{"subtasks": [{}]}', '{"subtasks": null}',
    '{"subtasks": [{"title": "x", "verify": "bad-shape"}]}',
    '{"subtasks": [{"title": "x", "description": null, "verify": {"cmd": 5, "expect": 9}}]}',
    '{"prompt": 5, "skills_to_invoke": 7, "pre_tool_hooks": {"x": 1}, "post_tool_hooks": 3}',
    '{"prompt": ["a", "b"], "effort_level": 9, "subagent": 3, "use_workflow": "yes"}',
    '{"prompt": null, "use_workflow": true, "workflow_definition": "not-a-dict"}',
    '{"' + "k" * 2000 + '": 1}',
    '{"subtasks": [' + ",".join('{"title":"t%d"}' % i for i in range(60)) + ']}',
]
_GARBAGE_RESP = ["content", None, "no-message", "no-content", "message-not-dict"]


class _FuzzBrain:
    def __init__(self, rng):
        self.rng = rng

    def chat(self, *, model=None, messages=None, **kw):
        shape = self.rng.choice(_GARBAGE_RESP)
        if shape == "content":
            return {"message": {"content": self.rng.choice(_GARBAGE_CONTENT)}}
        if shape is None:
            return None
        if shape == "no-message":
            return {}
        if shape == "no-content":
            return {"message": {}}
        return {"message": "not-a-dict"}


def _fuzz_replan(rng):
    def replan(*a, **k):
        return rng.choice([
            {"action": "keep"},
            {"action": "mutate", "add": "x", "remove": None},
            {"action": "mutate", "add": [1, 2], "remove": "st-001"},
            {"action": "mutate", "add": [{"title": 5}], "remove": [1, 2]},
            {}, {"action": "mutate"}, None, "garbage",
        ])
    return replan


class TestBrainFuzz(unittest.TestCase):
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

    def test_garbage_brain_always_reaches_done(self):
        goals = ["build a calculator", "build (1) add (2) sub (3) mul", "make a thing.py"]
        bad = []
        for seed in range(150):
            rng = random.Random(seed * 7 + 1)   # this multiplier surfaced the verify-path holes
            st = TaskState.create(rng.choice(goals), 1.0)
            st.setElaboratedGoal(st.meta["goal_raw"])
            st.save()
            orch = Orchestrator(brain=_FuzzBrain(rng), obs=simulation.SimObs(),
                                run_claude=simulation.simRunClaude, replan=_fuzz_replan(rng),
                                review=simulation.simReview)
            try:
                summary = orch.runFull(st, work_dir=str(self.work), auto_pr=False, control_mode="watch")
                if summary["status"] != "done":
                    bad.append((seed, summary["status"], summary.get("reason")))
            except Exception as e:  # noqa: BLE001 -- a raised exception is the worst outcome
                bad.append((seed, "RAISED", repr(e)))
        self.assertEqual(bad, [], f"brain fuzz produced non-done outcomes: {bad[:10]}")
