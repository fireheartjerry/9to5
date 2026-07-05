import unittest
from agents.planning.elaborator import judge
from agents.review import adversary_review


class TestJudgeElaboration(unittest.TestCase):
    def test_elaboration_review_type_registered(self):
        sys = adversary_review.systemFor("elaboration")
        self.assertIn("ELABORATED SPEC", sys)

    def test_judge_returns_verdict_dict(self):
        def chat(system, user, *, act=None, want_json=False, **k):
            return {"message": {"content": '{"verdict":"approved","concerns":[]}'}}
        out = judge.judgeElaboration("# Objective\ndo x", "do x", chat=chat)
        self.assertIn("verdict", out)

    def test_judge_never_raises(self):
        def boom(*a, **k):
            raise RuntimeError("brain down")
        out = judge.judgeElaboration("spec", "goal", chat=boom)
        self.assertEqual(out.get("verdict"), "unreviewed")


if __name__ == "__main__":
    unittest.main()
