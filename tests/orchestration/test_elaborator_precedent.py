import unittest
from agents.planning.elaborator import precedent


class TestPrecedent(unittest.TestCase):
    def test_success_and_failure_render(self):
        rf = lambda goal, k=3: [{"title": "add flag", "score": 0.9}]
        ff = lambda goal, k=2: [{"title": "broke build", "score": 0.7}]
        block = precedent.precedentBlock("do x", retrieve_fn=rf, fail_fn=ff)
        self.assertIn("PRECEDENT", block)
        self.assertIn("add flag", block)
        self.assertIn("broke build", block)

    def test_empty_returns_blank(self):
        block = precedent.precedentBlock("do x", retrieve_fn=lambda g, k=3: [], fail_fn=lambda g, k=2: [])
        self.assertEqual(block, "")

    def test_retrieve_error_is_swallowed(self):
        def boom(goal, k=3):
            raise RuntimeError("index down")
        block = precedent.precedentBlock("do x", retrieve_fn=boom, fail_fn=lambda g, k=2: [])
        self.assertEqual(block, "")

    def test_success_only(self):
        rf = lambda goal, k=3: [{"title": "prior spec", "score": 0.8}]
        block = precedent.precedentBlock("do x", retrieve_fn=rf, fail_fn=lambda g, k=2: [])
        self.assertIn("prior spec", block)
        self.assertNotIn("avoid", block)
