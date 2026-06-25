"""Correctness regressions from the gnarly audit:
- verify stdout_contains*/regex* families must require a clean exit (a crash that prints the needle
  was false-passing).
- an empty eval suite must record a transparent 'empty_suite' marker, not a fabricated 'scored'
  fitness (which polluted the SIE fitness series)."""
import unittest
from unittest import mock

from agents.verifier import _evaluate
from learning import eval_harness


class TestVerifyRequiresCleanExit(unittest.TestCase):
    def test_stdout_contains_fails_on_crash(self):
        self.assertFalse(_evaluate("stdout_contains:PASS", 1, "PASS\n"), "crash with needle false-passed")
        self.assertTrue(_evaluate("stdout_contains:PASS", 0, "PASS\n"))

    def test_stdout_regex_fails_on_crash(self):
        self.assertFalse(_evaluate("stdout_regex:OK", 1, "OK"))
        self.assertTrue(_evaluate("stdout_regex:OK", 0, "OK"))

    def test_compound_fails_on_crash(self):
        self.assertFalse(_evaluate("stdout_contains_all:A||B", 1, "A and B"))
        self.assertTrue(_evaluate("stdout_contains_all:A||B", 0, "A and B"))
        self.assertFalse(_evaluate("stdout_regex_all:A||B", 1, "A and B"))


class TestEmptyEvalSuite(unittest.TestCase):
    def test_empty_suite_records_marker_not_fitness(self):
        with mock.patch.object(eval_harness, "load_suite", return_value=[]), \
                mock.patch.object(eval_harness.experience, "record_eval") as rec:
            payload = eval_harness.run_suite(runner=lambda g: {"passed": True}, record=True)
        self.assertEqual(payload["status"], "empty_suite")
        self.assertNotIn("fitness", payload, "fabricated a fitness from an empty suite")
        self.assertEqual(payload["suite_size"], 0)
        rec.assert_called_once()


if __name__ == "__main__":
    unittest.main()
