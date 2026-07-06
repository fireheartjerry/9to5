"""Regression guard on the elaborator excellence CLAIM: the tier must measurably improve
grounding and/or prompt-signal versus flag-off, proven deterministically by the harness in
``tools/elaborator_eval.py`` (no Ollama, no network). Do NOT weaken these assertions -- the
point is a real, measured improvement."""
import unittest

from tools import elaborator_eval


class TestExcellenceEval(unittest.TestCase):
    def test_flag_on_not_worse_on_grounding_and_signal(self):
        results = elaborator_eval.runBattery()
        # Aggregate: flag-on grounding and prompt-signal must be >= flag-off (the tier's measurable value)
        off_g = sum(r["off"]["groundedness"] for r in results) / len(results)
        on_g = sum(r["on"]["groundedness"] for r in results) / len(results)
        off_s = sum(r["off"]["prompt_signal"] for r in results) / len(results)
        on_s = sum(r["on"]["prompt_signal"] for r in results) / len(results)
        self.assertGreaterEqual(on_g, off_g)
        self.assertGreaterEqual(on_s, off_s)

    def test_flag_on_strictly_improves_something(self):
        results = elaborator_eval.runBattery()
        on_g = sum(r["on"]["groundedness"] for r in results)
        off_g = sum(r["off"]["groundedness"] for r in results)
        on_s = sum(r["on"]["prompt_signal"] for r in results)
        off_s = sum(r["off"]["prompt_signal"] for r in results)
        self.assertTrue(on_g > off_g or on_s > off_s, "excellence tier must measurably improve grounding or signal")
