import unittest

from agents.planning.elaborator import self_review


class TestSelfReview(unittest.TestCase):
    def test_single_pass_only(self):
        calls = {"n": 0}

        def injected(system, user, *, act, want_json=False):
            calls["n"] += 1
            return {"message": {"content": "Inferred: X — because Y"}}

        out = self_review.reviewAssumptions("spec body", "goal", chat=injected)
        self.assertEqual(calls["n"], 1)  # exactly ONE pass, never a loop
        self.assertIn("Inferred:", out)

    def test_reward_frame_in_prompt(self):
        seen = {}

        def injected(system, user, *, act, want_json=False):
            seen["system"] = system
            return {"message": {"content": ""}}

        self_review.reviewAssumptions("spec", "goal", chat=injected)
        # I-CALM reward frame present (calibrated abstention, not free-form confidence)
        self.assertIn("+2", seen["system"])
        self.assertIn("abstain", seen["system"].lower())

    def test_degrades_to_empty_when_brain_down(self):
        def injected(system, user, *, act, want_json=False):
            return None

        self.assertEqual(self_review.reviewAssumptions("spec", "goal", chat=injected), "")
