"""R10 runner mechanics: arg-vector execution (no shell), cancel_check, timeout,
mandatory in-pipeline sanitization, and the one-release VResult compat shim."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from agents import verification, verifier
from agents.verification import Receipt, Verdict, VResult


class TestArgVectorExecution(unittest.TestCase):
    def test_split_cmd_preserves_windows_paths_and_quoted_spans(self):
        argv = verification._splitCmd('python "C:\\dir with space\\x.py" --flag')
        self.assertEqual(argv, ["python", "C:\\dir with space\\x.py", "--flag"])

    def test_split_cmd_python_c_body_is_one_arg(self):
        argv = verification._splitCmd('python -c "import os; print(os.getcwd())"')
        self.assertEqual(argv[:2], ["python", "-c"])
        self.assertEqual(argv[2], "import os; print(os.getcwd())")

    def test_shell_metacharacters_are_data_not_shell(self):
        # sanitize drops chaining for non-python-c cmds; for python -c the vector runner
        # hands the body to python literally -- nothing is ever shell-interpreted.
        with tempfile.TemporaryDirectory() as tmp:
            v = {"cmd": 'python -c "print(\'a && b\')"', "expect": "stdout_contains:a && b"}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertTrue(res["passed"], res.get("stderr"))

    def test_runs_real_command_and_captures_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = {"cmd": 'python -c "print(12345)"', "expect": "stdout_contains:12345"}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertTrue(res["passed"])
            self.assertIn("12345", res["stdout"])
            self.assertEqual(res["returncode"], 0)


class TestCancelAndTimeout(unittest.TestCase):
    def test_cancel_check_breaks_a_long_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = {"cmd": 'python -c "import time; time.sleep(30)"', "expect": "exit_zero"}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0},
                                           cancel_check=lambda: True)
            self.assertFalse(res["passed"])
            self.assertIs(res.receipt.verdict, Verdict.ERROR)
            self.assertIn("cancel", res.receipt.failure_feedback.lower())

    def test_timeout_yields_error_receipt(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(config, "VERIFY_TIMEOUT_SECONDS", 1):
            v = {"cmd": 'python -c "import time; time.sleep(30)"', "expect": "exit_zero"}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertFalse(res["passed"])
            self.assertIs(res.receipt.verdict, Verdict.ERROR)
            self.assertIn("TIMEOUT", res["stderr"])


class TestMandatorySanitizeInsidePipeline(unittest.TestCase):
    def test_placeholder_cmd_is_dropped_inside_the_runner(self):
        # call sites no longer pre-sanitize -- the pipeline must do it itself.
        with tempfile.TemporaryDirectory() as tmp:
            v = {"cmd": "python <ABSOLUTE path to file>", "expect": "exit_zero"}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertIsNone(res["cmd"])
            self.assertEqual(res["expect"], "executor_exit_zero")
            self.assertIs(res.receipt.verdict, Verdict.SKIPPED)

    def test_non_stdlib_import_is_dropped_inside_the_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = {"cmd": 'python -c "from fibonacci import fib; fib(3)"', "expect": "exit_zero"}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertIsNone(res["cmd"])
            self.assertIs(res.receipt.verdict, Verdict.SKIPPED)


class TestVResultCompatShim(unittest.TestCase):
    def test_legacy_dict_shape_and_typed_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = {"cmd": 'python -c "print(7)"', "expect": "exit_zero"}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertIsInstance(res, dict)
            for key in ("passed", "cmd", "expect", "returncode", "stdout", "stderr"):
                self.assertIn(key, res)
            self.assertEqual(res["cmd"], v["cmd"])          # original cmd string preserved
            self.assertEqual(res["expect"], "exit_zero")
            self.assertIsInstance(res, VResult)
            self.assertIsInstance(res.receipt, Receipt)
            self.assertTrue(res.passed)                     # attribute view == dict view
            self.assertEqual(res.passed, res["passed"])

    def test_no_cmd_falls_back_to_executor_exit(self):
        res = verifier.runVerification(None, tempfile.gettempdir(),
                                       {"ok": False, "returncode": 3, "stderr": "boom"})
        self.assertFalse(res["passed"])
        self.assertEqual(res["expect"], "executor_exit_zero")
        self.assertEqual(res["returncode"], 3)
        self.assertIn("boom", res["stderr"])

    def test_receipt_records_duration_and_expect_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = {"cmd": 'python -c "print(7)"', "expect": "stdout_contains:7"}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertEqual(res.receipt.expect_mode, "stdout_contains")
            self.assertGreaterEqual(res.receipt.duration_s, 0.0)
            self.assertEqual(res.receipt.annotations.get("expect_str"), "stdout_contains:7")


class TestAnnotations(unittest.TestCase):
    def test_annotate_never_changes_the_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = {"cmd": 'python -c "print(7)"', "expect": "exit_zero"}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            verification.annotate(res.receipt, "adversary_verdict", "challenged")
            verification.annotate(res.receipt, "evidence_headline", "NOT_VERIFIED")
            self.assertIs(res.receipt.verdict, Verdict.PASS)   # annotations are non-binding
            self.assertEqual(res.receipt.annotations["adversary_verdict"], "challenged")
