"""R10 runner mechanics: arg-vector execution (no shell), cancel_check, timeout,
mandatory in-pipeline sanitization, and the one-release VResult compat shim.

Also covers the missing-script fallback: a brain-authored verify referencing a helper
script that was never created (e.g. ``python check_unit_tests.py``) used to fail every
attempt with FileNotFoundError, burning all MAX_SUBTASK_ATTEMPTS retries on a structural
authoring defect rather than a real regression. runVerification now detects a missing
literal .py script and falls back to the executor's own exit status instead
(agents/verifier_runner.py::_verifyScriptMissing).

Also covers the companion fix: a broad pytest/unittest verify gets a longer timeout than
a narrow python -c check (agents/verifier_runner.py::_verifyTimeoutSeconds).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from agents import verification, verifier
from agents.verification import Receipt, Verdict, VResult
from agents.verifier_runner import _verifyTimeoutSeconds


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


# ---------------------------------------------------------------------------
# Missing-script fallback + companion timeout-shaping fix
# ---------------------------------------------------------------------------

def test_missing_script_falls_back_to_executor_ok(tmp_path):
    result = verifier.runVerification(
        {"cmd": "python check_unit_tests.py", "expect": "exit_zero"},
        str(tmp_path),
        {"ok": True, "returncode": 0},
    )
    assert result["passed"] is True
    assert result["cmd"] == "python check_unit_tests.py"
    assert "missing" in result["expect"]


def test_missing_script_falls_back_to_executor_failure(tmp_path):
    result = verifier.runVerification(
        {"cmd": "python check_integration_tests.py", "expect": "exit_zero"},
        str(tmp_path),
        {"ok": False, "returncode": 1, "stderr": "executor crashed"},
    )
    assert result["passed"] is False
    assert result["stderr"] == "executor crashed"


def test_existing_script_still_runs_normally(tmp_path):
    script = tmp_path / "check_ok.py"
    script.write_text("print('hi')\n", encoding="utf-8")
    result = verifier.runVerification(
        {"cmd": "python check_ok.py", "expect": "exit_zero"},
        str(tmp_path),
        {"ok": True, "returncode": 0},
    )
    assert result["passed"] is True
    assert result["cmd"] == "python check_ok.py"
    assert result["expect"] == "exit_zero"   # NOT the missing-script fallback path


def test_missing_glob_pattern_not_treated_as_missing_script(tmp_path):
    # A glob (*_test.py) isn't a literal path -- must not trip the missing-script fallback;
    # it runs (and fails naturally, e.g. no matches / bad shell) via the normal path.
    result = verifier.runVerification(
        {"cmd": "python -m pytest tests/*_test.py", "expect": "exit_zero"},
        str(tmp_path),
        {"ok": True, "returncode": 0},
    )
    assert result["expect"] == "exit_zero"   # normal path ran, not the missing-script shortcut


def test_suite_verify_gets_longer_timeout():
    assert _verifyTimeoutSeconds("python -m pytest tests/") == config.VERIFY_SUITE_TIMEOUT_SECONDS
    assert _verifyTimeoutSeconds("pytest tests/test_foo.py") == config.VERIFY_SUITE_TIMEOUT_SECONDS


def test_narrow_verify_keeps_tight_timeout():
    assert _verifyTimeoutSeconds('python -c "import sys; sys.exit(0)"') == config.VERIFY_TIMEOUT_SECONDS
    assert _verifyTimeoutSeconds("python check_ok.py") == config.VERIFY_TIMEOUT_SECONDS


def test_suite_timeout_longer_than_narrow_timeout():
    assert config.VERIFY_SUITE_TIMEOUT_SECONDS > config.VERIFY_TIMEOUT_SECONDS
