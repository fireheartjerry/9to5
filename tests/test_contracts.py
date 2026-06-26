"""The frozen domain dataclasses mirror their real producers (contracts.py)."""
import unittest

import contracts
from contracts import AgentDecision, ControlCommand, SubtaskSpec, Universe, VerificationResult

try:
    from tests.factories import make_subtask
except Exception:  # pragma: no cover - factories import shape varies by runner
    from factories import make_subtask


class TestSubtaskSpec(unittest.TestCase):
    def test_fromdict_wraps_a_real_factory_subtask(self):
        # Grounded against the canonical builder so field drift is caught here.
        d = make_subtask(title="do x")
        spec = SubtaskSpec.fromDict(d)
        self.assertEqual(spec.subtask_id, d["subtask_id"])
        self.assertEqual(spec.title, "do x")
        self.assertIsInstance(spec.depends_on, tuple)

    def test_is_frozen(self):
        spec = SubtaskSpec(subtask_id="st-001")
        with self.assertRaises(Exception):
            spec.title = "mutated"  # frozen


class TestVerificationResult(unittest.TestCase):
    def test_fromdict_matches_verifier_output_shape(self):
        # Exact mirror of agents/verifier.runVerification() return.
        raw = {"passed": True, "cmd": "pytest -q", "expect": "exit_zero",
               "returncode": 0, "stdout": "1 passed", "stderr": ""}
        r = VerificationResult.fromDict(raw)
        self.assertTrue(r.passed)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.cmd, "pytest -q")


class TestUniverse(unittest.TestCase):
    def test_fromdict_none_is_empty_not_crash(self):
        u = Universe.fromDict(None)
        self.assertEqual(u.hard_boundaries, ())

    def test_fromdict_preserves_boundaries(self):
        u = Universe.fromDict({"hard_boundaries": [".env", ".git"]})
        self.assertIn(".env", u.hard_boundaries)


class TestSmallValues(unittest.TestCase):
    def test_control_command(self):
        c = ControlCommand(name="skip", arg="st-001")
        self.assertEqual((c.name, c.arg), ("skip", "st-001"))

    def test_agent_decision_defaults_are_safe(self):
        d = AgentDecision()
        self.assertEqual(d.risk, "low")
        self.assertFalse(d.needs_human_review)

    def test_module_exports_the_spine(self):
        for name in ("Goal", "ElaboratedGoal", "Universe", "SubtaskSpec",
                     "VerificationResult", "ControlCommand", "AgentDecision"):
            self.assertTrue(hasattr(contracts, name), name)


if __name__ == "__main__":
    unittest.main()
