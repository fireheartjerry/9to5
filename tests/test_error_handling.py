"""Tests for error_handling -- retryTask retry-before-alert and diagnostic logging.

Acceptance command: python C:\\9to5\\tests\\test_error_handling.py  (expect exit_zero)
"""
from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from error_handling import MAX_RETRIES, RETRY_DELAY_SECONDS, RetryExhausted, retryTask


class TestRetryTaskSuccess(unittest.TestCase):
    def test_succeeds_on_first_try(self):
        fn = MagicMock(return_value="done")
        result = retryTask(fn)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], "done")
        self.assertEqual(result["attempts"], 1)
        fn.assert_called_once()

    def test_succeeds_on_second_try(self):
        fn = MagicMock(side_effect=[RuntimeError("fail"), "recovered"])
        with patch("error_handling.time.sleep"):
            result = retryTask(fn, max_retries=3, delay=0.1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts"], 2)

    def test_passes_args_and_kwargs(self):
        fn = MagicMock(return_value=42)
        result = retryTask(fn, args=(1, 2), kwargs={"x": 3})
        fn.assert_called_once_with(1, 2, x=3)
        self.assertTrue(result["ok"])

    def test_result_dict_keys(self):
        fn = MagicMock(return_value=None)
        result = retryTask(fn)
        self.assertIn("ok", result)
        self.assertIn("result", result)
        self.assertIn("attempts", result)


class TestRetryTaskExhaustion(unittest.TestCase):
    def test_raises_retry_exhausted_without_on_alert(self):
        fn = MagicMock(side_effect=RuntimeError("boom"))
        with patch("error_handling.time.sleep"):
            with self.assertRaises(RetryExhausted):
                retryTask(fn, max_retries=MAX_RETRIES)
        self.assertEqual(fn.call_count, MAX_RETRIES)

    def test_retry_exhausted_is_runtime_error(self):
        fn = MagicMock(side_effect=ValueError("bad"))
        with patch("error_handling.time.sleep"):
            with self.assertRaises(RuntimeError):
                retryTask(fn, max_retries=1)

    def test_calls_on_alert_instead_of_raising(self):
        fn = MagicMock(side_effect=IOError("disk full"))
        alert = MagicMock()
        with patch("error_handling.time.sleep"):
            result = retryTask(fn, max_retries=3, on_alert=alert)
        self.assertFalse(result["ok"])
        self.assertEqual(result["attempts"], 3)
        alert.assert_called_once()

    def test_on_alert_receives_error_msg_and_attempt_count(self):
        fn = MagicMock(side_effect=ValueError("broken"))
        captured: dict = {}

        def capture(err_msg: str, attempts: int) -> None:
            captured["err"] = err_msg
            captured["attempts"] = attempts

        with patch("error_handling.time.sleep"):
            retryTask(fn, max_retries=2, on_alert=capture)
        self.assertIn("ValueError", captured["err"])
        self.assertEqual(captured["attempts"], 2)

    def test_error_dict_contains_last_exception_type(self):
        fn = MagicMock(side_effect=KeyError("missing"))
        with patch("error_handling.time.sleep"):
            result = retryTask(fn, max_retries=1, on_alert=lambda *a: None)
        self.assertFalse(result["ok"])
        self.assertIn("KeyError", result["error"])

    def test_exactly_three_attempts_before_alert(self):
        """Core requirement: exactly MAX_RETRIES=3 attempts, then alert fires once."""
        fn = MagicMock(side_effect=RuntimeError("fail"))
        alert = MagicMock()
        with patch("error_handling.time.sleep"):
            retryTask(fn, max_retries=3, on_alert=alert)
        self.assertEqual(fn.call_count, 3)
        alert.assert_called_once()


class TestRetryTaskSleep(unittest.TestCase):
    def test_sleeps_between_attempts_not_after_last(self):
        """sleep must fire max_retries-1 times (between attempts, never after the last)."""
        fn = MagicMock(side_effect=RuntimeError("fail"))
        with patch("error_handling.time.sleep") as mock_sleep:
            with self.assertRaises(RetryExhausted):
                retryTask(fn, max_retries=3, delay=0.5)
        self.assertEqual(mock_sleep.call_count, 2)

    def test_sleep_uses_configured_delay(self):
        fn = MagicMock(side_effect=[RuntimeError("once"), "ok"])
        with patch("error_handling.time.sleep") as mock_sleep:
            retryTask(fn, max_retries=3, delay=2.5)
        mock_sleep.assert_called_once_with(2.5)

    def test_no_sleep_on_single_attempt_failure(self):
        fn = MagicMock(side_effect=RuntimeError("instant"))
        with patch("error_handling.time.sleep") as mock_sleep:
            with self.assertRaises(RetryExhausted):
                retryTask(fn, max_retries=1)
        mock_sleep.assert_not_called()


class TestRetryTaskLogging(unittest.TestCase):
    def test_warning_logged_on_each_failure(self):
        fn = MagicMock(side_effect=[RuntimeError("e1"), RuntimeError("e2"), "ok"])
        with patch("error_handling.time.sleep"):
            with self.assertLogs("9to5.error_handling", level=logging.WARNING) as cm:
                retryTask(fn, max_retries=3, delay=0)
        warnings = [m for m in cm.output if "WARNING" in m]
        self.assertEqual(len(warnings), 2)

    def test_critical_logged_on_exhaustion(self):
        fn = MagicMock(side_effect=RuntimeError("fatal"))
        with patch("error_handling.time.sleep"):
            with self.assertLogs("9to5.error_handling", level=logging.CRITICAL) as cm:
                retryTask(fn, max_retries=2, on_alert=lambda *a: None)
        criticals = [m for m in cm.output if "CRITICAL" in m]
        self.assertEqual(len(criticals), 1)

    def test_info_logged_on_recovery(self):
        fn = MagicMock(side_effect=[RuntimeError("first"), "recovered"])
        with patch("error_handling.time.sleep"):
            with self.assertLogs("9to5.error_handling", level=logging.INFO) as cm:
                retryTask(fn, max_retries=3, delay=0)
        self.assertTrue(any("succeeded" in m for m in cm.output))

    def test_warning_includes_attempt_number(self):
        fn = MagicMock(side_effect=RuntimeError("boom"))
        with patch("error_handling.time.sleep"):
            with self.assertLogs("9to5.error_handling", level=logging.WARNING) as cm:
                retryTask(fn, max_retries=1, on_alert=lambda *a: None)
        self.assertTrue(any("1/1" in m for m in cm.output))

    def test_critical_includes_error_detail(self):
        fn = MagicMock(side_effect=ValueError("specific error detail"))
        with patch("error_handling.time.sleep"):
            with self.assertLogs("9to5.error_handling", level=logging.CRITICAL) as cm:
                retryTask(fn, max_retries=1, on_alert=lambda *a: None)
        self.assertTrue(any("specific error detail" in m for m in cm.output))


class TestConstants(unittest.TestCase):
    def test_max_retries_is_three(self):
        self.assertEqual(MAX_RETRIES, 3)

    def test_retry_delay_is_positive(self):
        self.assertGreater(RETRY_DELAY_SECONDS, 0)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--verify-recurring-task-handling", action="store_true", default=False)
    known, remaining = parser.parse_known_args()

    if known.verify_recurring_task_handling:
        # Run the full suite; exit 0 on success, 1 on any failure.
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromModule(sys.modules[__name__])
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        sys.exit(0 if result.wasSuccessful() else 1)
    else:
        unittest.main(argv=[sys.argv[0]] + remaining)
