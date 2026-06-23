"""Unit tests for SIE reward modeling + calibrator (learning/reward.py)."""
import unittest

from learning import reward


class TestReward(unittest.TestCase):
    def test_clean_first_pass_high_reward(self):
        r = reward.composite_reward(
            {"verify_passed": 1, "attempt_count": 1, "adversary_verdict": "approved"})
        self.assertGreater(r, 0.8)

    def test_failure_low_reward(self):
        r = reward.composite_reward({"verify_passed": 0, "attempt_count": 3})
        self.assertLess(r, 0.3)

    def test_retry_pass_between(self):
        clean = reward.composite_reward({"verify_passed": 1, "attempt_count": 1})
        retried = reward.composite_reward({"verify_passed": 1, "attempt_count": 3})
        self.assertGreater(clean, retried)   # first-pass beats a scrappy pass

    def test_signals_shape(self):
        self.assertEqual(len(reward.signals({"verify_passed": 1})), 5)


class TestCalibrator(unittest.TestCase):
    def test_fit_predicts_success_higher(self):
        rows = []
        for _ in range(40):
            rows.append({"verify_passed": 1, "attempt_count": 1, "adversary_verdict": "approved"})
            rows.append({"verify_passed": 0, "attempt_count": 3, "adversary_verdict": "challenged"})
        cal = reward.Calibrator().fit(rows, epochs=400, lr=0.5)
        p_win = cal.predict({"verify_passed": 1, "attempt_count": 1, "adversary_verdict": "approved"})
        p_lose = cal.predict({"verify_passed": 0, "attempt_count": 3, "adversary_verdict": "challenged"})
        self.assertGreater(p_win, 0.7)
        self.assertLess(p_lose, 0.3)
        self.assertGreater(p_win, p_lose)   # calibrated ordering matches reality

    def test_fit_empty_is_noop(self):
        cal = reward.Calibrator().fit([])
        self.assertTrue(0.0 <= cal.predict({"verify_passed": 1}) <= 1.0)


if __name__ == "__main__":
    unittest.main()
