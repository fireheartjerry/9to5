"""Acceptance tests for retry_policy.RetryPolicy.

Acceptance command: python C:\\9to5\\tests\\test_retry_policy.py  (expect exit_zero)
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from error_handling import MAX_RETRIES, RETRY_DELAY_SECONDS, RetryExhausted
from retry_policy import RetryPolicy


class TestRetryPolicyDefaults(unittest.TestCase):
    def test_default_max_retries(self):
        policy = RetryPolicy()
        self.assertEqual(policy.max_retries, MAX_RETRIES)

    def test_default_delay(self):
        policy = RetryPolicy()
        self.assertEqual(policy.delay, RETRY_DELAY_SECONDS)

    def test_default_on_alert_is_none(self):
        policy = RetryPolicy()
        self.assertIsNone(policy.on_alert)

    def test_custom_values_stored(self):
        alert = MagicMock()
        policy = RetryPolicy(max_retries=5, delay=0.5, on_alert=alert)
        self.assertEqual(policy.max_retries, 5)
        self.assertEqual(policy.delay, 0.5)
        self.assertIs(policy.on_alert, alert)


class TestRetryPolicyExecuteSuccess(unittest.TestCase):
    def test_success_first_attempt(self):
        fn = MagicMock(return_value="ok")
        result = RetryPolicy(max_retries=3).execute(fn)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], "ok")
        self.assertEqual(result["attempts"], 1)

    def test_result_contains_policy_ref(self):
        fn = MagicMock(return_value=42)
        policy = RetryPolicy()
        result = policy.execute(fn)
        self.assertIs(result["policy"], policy)

    def test_passes_args_and_kwargs(self):
        fn = MagicMock(return_value=True)
        RetryPolicy().execute(fn, args=(1, 2), kwargs={"x": 9})
        fn.assert_called_once_with(1, 2, x=9)

    def test_succeeds_on_retry(self):
        fn = MagicMock(side_effect=[RuntimeError("first"), "recovered"])
        with patch("error_handling.time.sleep"):
            result = RetryPolicy(max_retries=3, delay=0).execute(fn)
        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts"], 2)


class TestRetryPolicyExhaustion(unittest.TestCase):
    def test_raises_retry_exhausted_without_alert(self):
        fn = MagicMock(side_effect=RuntimeError("boom"))
        policy = RetryPolicy(max_retries=3)
        with patch("error_handling.time.sleep"):
            with self.assertRaises(RetryExhausted):
                policy.execute(fn)
        self.assertEqual(fn.call_count, 3)

    def test_exactly_three_attempts_before_alert(self):
        fn = MagicMock(side_effect=RuntimeError("fail"))
        alert = MagicMock()
        policy = RetryPolicy(max_retries=3, on_alert=alert)
        with patch("error_handling.time.sleep"):
            result = policy.execute(fn)
        self.assertEqual(fn.call_count, 3)
        alert.assert_called_once()
        self.assertFalse(result["ok"])

    def test_on_alert_receives_error_msg_and_attempt_count(self):
        captured: dict = {}

        def capture(msg: str, attempts: int) -> None:
            captured["msg"] = msg
            captured["attempts"] = attempts

        fn = MagicMock(side_effect=ValueError("bad value"))
        policy = RetryPolicy(max_retries=2, on_alert=capture)
        with patch("error_handling.time.sleep"):
            policy.execute(fn)
        self.assertIn("ValueError", captured["msg"])
        self.assertEqual(captured["attempts"], 2)

    def test_error_result_contains_exception_type(self):
        fn = MagicMock(side_effect=KeyError("missing"))
        policy = RetryPolicy(max_retries=1, on_alert=lambda *a: None)
        with patch("error_handling.time.sleep"):
            result = policy.execute(fn)
        self.assertIn("KeyError", result["error"])


class TestRetryPolicySleepBehaviour(unittest.TestCase):
    def test_sleeps_between_attempts_not_after_last(self):
        fn = MagicMock(side_effect=RuntimeError("fail"))
        policy = RetryPolicy(max_retries=3, delay=0.1, on_alert=lambda *a: None)
        with patch("error_handling.time.sleep") as mock_sleep:
            policy.execute(fn)
        # max_retries-1 sleeps: between attempt 1-2 and 2-3, none after 3
        self.assertEqual(mock_sleep.call_count, 2)

    def test_sleep_uses_configured_delay(self):
        fn = MagicMock(side_effect=[RuntimeError("once"), "ok"])
        policy = RetryPolicy(max_retries=3, delay=7.5)
        with patch("error_handling.time.sleep") as mock_sleep:
            policy.execute(fn)
        mock_sleep.assert_called_once_with(7.5)


class TestRetryPolicyComposition(unittest.TestCase):
    def test_with_alert_returns_new_policy(self):
        base = RetryPolicy(max_retries=5, delay=2.0)
        alert = MagicMock()
        derived = base.with_alert(alert)
        self.assertIsNot(derived, base)
        self.assertEqual(derived.max_retries, 5)
        self.assertEqual(derived.delay, 2.0)
        self.assertIs(derived.on_alert, alert)

    def test_with_alert_does_not_mutate_original(self):
        base = RetryPolicy(max_retries=3)
        base.with_alert(MagicMock())
        self.assertIsNone(base.on_alert)

    def test_with_retries_returns_new_policy(self):
        base = RetryPolicy(max_retries=3, delay=1.0)
        derived = base.with_retries(10)
        self.assertIsNot(derived, base)
        self.assertEqual(derived.max_retries, 10)
        self.assertEqual(derived.delay, base.delay)

    def test_subclass_can_override_execute(self):
        """RetryPolicy is extensible: subclass can wrap execute."""

        class InstrumentedPolicy(RetryPolicy):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.call_log: list = []

            def execute(self, fn, *, args=(), kwargs=None):
                self.call_log.append(fn)
                return super().execute(fn, args=args, kwargs=kwargs)

        fn = MagicMock(return_value="data")
        policy = InstrumentedPolicy(max_retries=1)
        result = policy.execute(fn)
        self.assertTrue(result["ok"])
        self.assertIn(fn, policy.call_log)


if __name__ == "__main__":
    unittest.main(verbosity=2)
