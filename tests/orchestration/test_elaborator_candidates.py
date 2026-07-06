import unittest
from agents.planning.elaborator import candidates


class TestBudget(unittest.TestCase):
    def test_precise_goal_one(self):
        self.assertEqual(candidates.budgetFor("x", is_vague=False, precedent_hits=0, max_n=5), 1)

    def test_vague_no_precedent_scales_up(self):
        n = candidates.budgetFor("improve everything", is_vague=True, precedent_hits=0, max_n=5)
        self.assertGreaterEqual(n, 3)

    def test_respects_max(self):
        n = candidates.budgetFor("x", is_vague=True, precedent_hits=0, max_n=2)
        self.assertLessEqual(n, 2)

    def test_vague_with_precedent_lower(self):
        few = candidates.budgetFor("x", is_vague=True, precedent_hits=3, max_n=5)
        none = candidates.budgetFor("x", is_vague=True, precedent_hits=0, max_n=5)
        self.assertLessEqual(few, none)


class TestGenerate(unittest.TestCase):
    def test_generates_n_candidates(self):
        gen = lambda goal, wd, stance: f"spec-{stance}"
        out = candidates.generate("g", None, n=2, gen_fn=gen)
        self.assertEqual(len(out), 2)
        self.assertTrue(all("id" in c and "spec" in c and "stance" in c for c in out))
        self.assertEqual(out[0]["spec"], f"spec-{candidates.STANCES[0]}")


class TestSelect(unittest.TestCase):
    def test_selects_highest_weight(self):
        cands = [{"id": "a", "spec": "A"}, {"id": "b", "spec": "B"}]
        best = candidates.selectBest(cands, weight_fn=lambda c: 1.0 if c["id"] == "b" else 0.0)
        self.assertEqual(best["id"], "b")

    def test_empty_returns_none(self):
        self.assertIsNone(candidates.selectBest([], weight_fn=lambda c: 0.0))


class TestMerit(unittest.TestCase):
    def test_monotonic(self):
        base = candidates.meritWeight({}, groundedness=0.0, precedent=0.0, predicted=0.0, elevated=0)
        more = candidates.meritWeight({}, groundedness=1.0, precedent=1.0, predicted=1.0, elevated=0)
        self.assertGreater(more, base)

    def test_elevated_penalizes(self):
        a = candidates.meritWeight({}, predicted=1.0, elevated=0)
        b = candidates.meritWeight({}, predicted=1.0, elevated=2)
        self.assertGreater(a, b)
