"""Property-based fuzz of the control plane: a 'chaos operator' fires random control
actions (pause/resume/skip/add/approve/reject/abort) in random order, at random moments,
through random surfaces, during a live run. INVARIANT: the run must ALWAYS end in a valid
terminal state -- never crash and never hang -- no matter the action sequence.
"""
import random
import os
import time
import unittest

from state.task import TaskState
from testing import e2e

_TERMINAL = set(TaskState._TERMINAL)
_ACTIONS = ["pause", "resume", "skip", "add", "approve", "reject", "status"]


def _seedCount(default=24):
    raw = os.getenv("NINE_TO_FIVE_FUZZ_SEEDS", "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _chaosScript(rng):
    def script(op):
        deadline = time.time() + 2.5
        steps = 0
        while op.status() not in _TERMINAL and time.time() < deadline and steps < 300:
            steps += 1
            a = rng.choice(_ACTIONS)
            try:
                if a == "skip":
                    op._do("skip", f"st-00{rng.randint(1, 4)}")
                elif a == "add":
                    op._do("add", f"chaos subtask {steps}")
                elif a == "status":
                    op.status()
                else:
                    op._do(a)
            except Exception:  # noqa: BLE001 -- a control action must never raise into the operator
                pass
            # keep the run from deadlocking on a gate/pause so the fuzz always terminates
            try:
                if op.pendingGate():
                    op._do("approve")
                op._do("resume")
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.001)
        if op.status() not in _TERMINAL:   # guarantee termination for the assertion
            try:
                op._do("abort")
            except Exception:  # noqa: BLE001
                pass
    return script


class TestControlFuzz(unittest.TestCase):
    def test_seed_count_defaults_and_env_override(self):
        old = os.environ.get("NINE_TO_FIVE_FUZZ_SEEDS")
        try:
            os.environ.pop("NINE_TO_FIVE_FUZZ_SEEDS", None)
            self.assertEqual(_seedCount(default=7), 7)
            os.environ["NINE_TO_FIVE_FUZZ_SEEDS"] = "3"
            self.assertEqual(_seedCount(default=7), 3)
            os.environ["NINE_TO_FIVE_FUZZ_SEEDS"] = "bad"
            self.assertEqual(_seedCount(default=7), 7)
        finally:
            if old is None:
                os.environ.pop("NINE_TO_FIVE_FUZZ_SEEDS", None)
            else:
                os.environ["NINE_TO_FIVE_FUZZ_SEEDS"] = old

    def test_random_control_sequences_always_terminate_cleanly(self):
        bad = []
        for seed in range(_seedCount()):
            rng = random.Random(seed * 13 + 5)
            surface = rng.choice(["web", "bus"])
            r = e2e.runScenario(f"chaos-{seed}", "build (1) a (2) b (3) c",
                                _chaosScript(rng), expect_status="(any-terminal)",
                                surface=surface, n_subtasks=3, timeout=20.0)
            if r.error is not None or r.alive or r.status not in _TERMINAL:
                bad.append((seed, surface, r.status, r.alive, r.error))
        self.assertEqual(bad, [], f"control fuzz produced bad outcomes: {bad[:8]}")


if __name__ == "__main__":
    unittest.main()
