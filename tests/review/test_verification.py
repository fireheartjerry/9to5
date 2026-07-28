"""Unit tests for agents/review/verification.py -- public methods and error handling.

Covers all public exports:
  verdictFor, annotate, VResult, Receipt, runReceipt, receiptToVResult, VerifyCancelled
Plus error handling for ValueError, TypeError, KeyError injected via mocks.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.review.verification import (
    Receipt,
    Verdict,
    VResult,
    annotate,
    receiptToVResult,
    runReceipt,
    verdictFor,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _receipt(*, verdict: Verdict = Verdict.PASS, cmd: tuple[str, ...] = (),
             rc: int | None = 0, expect_mode: str = "exit_zero",
             matched: tuple[str, ...] = (), missing: tuple[str, ...] = (),
             diff_files: tuple[str, ...] = (), duration_s: float = 0.0,
             failure_feedback: str = "", annotations: dict | None = None) -> Receipt:
    return Receipt(verdict=verdict, cmd=cmd, rc=rc, expect_mode=expect_mode,
                   matched=matched, missing=missing, diff_files=diff_files,
                   duration_s=duration_s, failure_feedback=failure_feedback,
                   annotations={} if annotations is None else annotations)


def _contained_authority(work_dir: str, *, runner=None):
    from agents.review.verification import issueDiagnosticVerificationCommandAuthority

    def contained(request):
        return subprocess.run(
            list(request.argv),
            cwd=request.work_dir,
            capture_output=True,
            text=True,
            timeout=request.timeout_seconds,
            check=False,
        )

    return issueDiagnosticVerificationCommandAuthority(
        transaction_id="tx_verification_test",
        proposed_revision="1" * 40,
        resource_id="verifier_test",
        work_dir=work_dir,
        image_digest="2" * 64,
        security_profile_digest="3" * 64,
        command_policy_digest="4" * 64,
        watchdog_generation=1,
        deadline="2099-01-01T00:00:00+00:00",
        runner=runner or contained,
    )


# ---------------------------------------------------------------------------
# verdictFor
# ---------------------------------------------------------------------------

class TestVerdictFor(unittest.TestCase):
    """Pure function: (rc, output, expect) -> (verdict, matched, missing)."""

    def test_exit_zero_pass(self):
        v, m, s = verdictFor(0, "", "exit_zero")
        self.assertIs(v, Verdict.PASS)
        self.assertEqual(m, ())
        self.assertEqual(s, ())

    def test_exit_zero_fail(self):
        self.assertIs(verdictFor(1, "", "exit_zero")[0], Verdict.FAIL)

    def test_none_rc_is_error(self):
        self.assertIs(verdictFor(None, "", "exit_zero")[0], Verdict.ERROR)

    def test_none_expect_is_error(self):
        self.assertIs(verdictFor(0, "ok", None)[0], Verdict.ERROR)

    def test_empty_expect_is_error(self):
        self.assertIs(verdictFor(0, "ok", "")[0], Verdict.ERROR)

    def test_whitespace_expect_is_error(self):
        self.assertIs(verdictFor(0, "ok", "  ")[0], Verdict.ERROR)

    def test_unknown_shape_is_error(self):
        self.assertIs(verdictFor(0, "ok", "some_unknown_mode")[0], Verdict.ERROR)

    def test_int_expect_is_error(self):
        self.assertIs(verdictFor(0, "ok", 42)[0], Verdict.ERROR)

    def test_none_output_treated_as_empty(self):
        v, _, missing = verdictFor(0, None, "stdout_contains:needle")
        self.assertIs(v, Verdict.FAIL)
        self.assertIn("needle", missing)

    def test_stdout_contains_pass(self):
        v, matched, _ = verdictFor(0, "hello world", "stdout_contains:hello")
        self.assertIs(v, Verdict.PASS)
        self.assertIn("hello", matched)

    def test_stdout_contains_missing_fails(self):
        v, _, missing = verdictFor(0, "hello", "stdout_contains:NOPE")
        self.assertIs(v, Verdict.FAIL)
        self.assertIn("NOPE", missing)

    def test_stdout_contains_nonzero_rc_fails(self):
        self.assertIs(verdictFor(1, "hello", "stdout_contains:hello")[0], Verdict.FAIL)

    def test_stdout_regex_pass(self):
        v, _, _ = verdictFor(0, "value=42", r"stdout_regex:value=\d+")
        self.assertIs(v, Verdict.PASS)

    def test_stdout_regex_bad_pattern_is_error(self):
        self.assertIs(verdictFor(0, "ok", "stdout_regex:[bad")[0], Verdict.ERROR)

    def test_stdout_contains_all_pass(self):
        v, matched, missing = verdictFor(0, "a b c", "stdout_contains_all:a||b||c")
        self.assertIs(v, Verdict.PASS)
        self.assertEqual(set(matched), {"a", "b", "c"})
        self.assertEqual(missing, ())

    def test_stdout_contains_all_partial_fail(self):
        v, matched, missing = verdictFor(0, "a", "stdout_contains_all:a||b")
        self.assertIs(v, Verdict.FAIL)
        self.assertIn("b", missing)
        self.assertIn("a", matched)

    def test_stdout_contains_all_empty_needles_error(self):
        self.assertIs(verdictFor(0, "ok", "stdout_contains_all:")[0], Verdict.ERROR)

    def test_stdout_regex_all_bad_pattern_error(self):
        self.assertIs(verdictFor(0, "ok", "stdout_regex_all:[bad")[0], Verdict.ERROR)

    def test_stdout_regex_all_empty_error(self):
        self.assertIs(verdictFor(0, "ok", "stdout_regex_all:")[0], Verdict.ERROR)


# ---------------------------------------------------------------------------
# annotate
# ---------------------------------------------------------------------------

class TestAnnotate(unittest.TestCase):
    def test_adds_key(self):
        r = _receipt()
        annotate(r, "k", "v")
        self.assertEqual(r.annotations["k"], "v")

    def test_overwrites_existing(self):
        r = _receipt()
        annotate(r, "k", "v1")
        annotate(r, "k", "v2")
        self.assertEqual(r.annotations["k"], "v2")

    def test_accepts_complex_value(self):
        r = _receipt()
        annotate(r, "data", [1, 2, 3])
        self.assertEqual(r.annotations["data"], [1, 2, 3])


# ---------------------------------------------------------------------------
# VResult
# ---------------------------------------------------------------------------

class TestVResult(unittest.TestCase):
    def _make(self, passed: bool) -> VResult:
        r = _receipt(verdict=Verdict.PASS if passed else Verdict.FAIL)
        return VResult(r, {"passed": passed, "cmd": None, "expect": "exit_zero",
                           "returncode": 0, "stdout": "", "stderr": ""})

    def test_passed_true(self):
        self.assertTrue(self._make(True).passed)

    def test_passed_false(self):
        self.assertFalse(self._make(False).passed)

    def test_receipt_attr(self):
        r = _receipt()
        vr = VResult(r, {"passed": True})
        self.assertIs(vr.receipt, r)

    def test_dict_access(self):
        vr = self._make(True)
        self.assertEqual(vr["returncode"], 0)

    def test_absent_passed_key_is_false(self):
        r = _receipt()
        self.assertFalse(VResult(r, {}).passed)


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------

class TestReceipt(unittest.TestCase):
    def test_passed_for_pass_verdict(self):
        self.assertTrue(_receipt(verdict=Verdict.PASS).passed)

    def test_not_passed_for_fail(self):
        self.assertFalse(_receipt(verdict=Verdict.FAIL).passed)

    def test_not_passed_for_error(self):
        self.assertFalse(_receipt(verdict=Verdict.ERROR).passed)

    def test_not_passed_for_skipped(self):
        self.assertFalse(_receipt(verdict=Verdict.SKIPPED).passed)

    def test_frozen_prevents_attribute_set(self):
        r = _receipt()
        with self.assertRaises((AttributeError, TypeError)):
            r.verdict = Verdict.FAIL  # type: ignore[misc]


# ---------------------------------------------------------------------------
# receiptToVResult
# ---------------------------------------------------------------------------

class TestReceiptToVResult(unittest.TestCase):
    def test_pass_receipt(self):
        r = _receipt(verdict=Verdict.PASS, rc=0, expect_mode="exit_zero",
                     cmd=("python", "t.py"),
                     annotations={"stdout": "out", "stderr": "",
                                  "cmd_str": "python t.py", "expect_str": "exit_zero"})
        vr = receiptToVResult(r)
        self.assertTrue(vr["passed"])
        self.assertEqual(vr["stdout"], "out")
        self.assertIs(vr.receipt, r)

    def test_fail_receipt(self):
        r = _receipt(verdict=Verdict.FAIL, rc=1, expect_mode="exit_zero",
                     failure_feedback="rc=1",
                     annotations={"stdout": "", "stderr": "err",
                                  "cmd_str": "x", "expect_str": "exit_zero"})
        vr = receiptToVResult(r)
        self.assertFalse(vr["passed"])

    def test_skipped_executor_ok(self):
        r = _receipt(verdict=Verdict.SKIPPED, rc=0, expect_mode="executor_exit_zero",
                     annotations={"stdout": "", "stderr": "", "executor_ok": True})
        vr = receiptToVResult(r)
        self.assertTrue(vr["passed"])
        self.assertIsNone(vr["cmd"])

    def test_skipped_executor_fail(self):
        r = _receipt(verdict=Verdict.SKIPPED, rc=1, expect_mode="executor_exit_zero",
                     annotations={"stdout": "", "stderr": "crash", "executor_ok": False})
        vr = receiptToVResult(r)
        self.assertFalse(vr["passed"])


# ---------------------------------------------------------------------------
# runReceipt -- no-cmd / skipped path
# ---------------------------------------------------------------------------

class TestRunReceiptSkipped(unittest.TestCase):
    def test_none_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = runReceipt(None, tmp, {"ok": True, "returncode": 0})
            self.assertIs(r.verdict, Verdict.SKIPPED)

    def test_verify_without_cmd(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = runReceipt({"expect": "exit_zero"}, tmp, {"ok": True})
            self.assertIs(r.verdict, Verdict.SKIPPED)

    def test_non_dict_executor_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = runReceipt(None, tmp, "bad")
            self.assertIs(r.verdict, Verdict.SKIPPED)

    def test_none_executor_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = runReceipt(None, tmp, None)
            self.assertIs(r.verdict, Verdict.SKIPPED)


# ---------------------------------------------------------------------------
# runReceipt -- happy path
# ---------------------------------------------------------------------------

class TestRunReceiptHappyPath(unittest.TestCase):
    def test_exit_zero_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "ok.py"
            script.write_text('print("ok")\n', encoding="utf-8")
            r = runReceipt({"cmd": f'python "{script}"', "expect": "exit_zero"},
                           tmp, {"ok": True}, authority=_contained_authority(tmp))
            self.assertIs(r.verdict, Verdict.PASS)
            self.assertTrue(r.passed)

    def test_stdout_contains_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "s.py"
            script.write_text('print("MARKER")\n', encoding="utf-8")
            r = runReceipt({"cmd": f'python "{script}"', "expect": "stdout_contains:MARKER"},
                           tmp, {"ok": True}, authority=_contained_authority(tmp))
            self.assertIs(r.verdict, Verdict.PASS)

    def test_stdout_contains_fail_when_needle_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "s.py"
            script.write_text('print("nope")\n', encoding="utf-8")
            r = runReceipt({"cmd": f'python "{script}"', "expect": "stdout_contains:MARKER"},
                           tmp, {"ok": True}, authority=_contained_authority(tmp))
            self.assertIs(r.verdict, Verdict.FAIL)

    def test_nonzero_rc_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fail.py"
            script.write_text("raise SystemExit(1)\n", encoding="utf-8")
            r = runReceipt({"cmd": f'python "{script}"', "expect": "exit_zero"},
                           tmp, {"ok": True}, authority=_contained_authority(tmp))
            self.assertIs(r.verdict, Verdict.FAIL)
            self.assertEqual(r.rc, 1)

    def test_result_has_annotations(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "ok.py"
            script.write_text('print("ok")\n', encoding="utf-8")
            r = runReceipt({"cmd": f'python "{script}"', "expect": "exit_zero"},
                           tmp, {"ok": True}, authority=_contained_authority(tmp))
            self.assertIn("stdout", r.annotations)
            self.assertIn("cmd_str", r.annotations)


# ---------------------------------------------------------------------------
# runReceipt -- error handling (new guards)
# ---------------------------------------------------------------------------

class TestRunReceiptErrorHandling(unittest.TestCase):
    def test_spawn_error_returns_error_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = runReceipt({"cmd": "no_such_binary_xyz123 --flag", "expect": "exit_zero"},
                           tmp, {"ok": True}, authority=_contained_authority(tmp))
            self.assertIs(r.verdict, Verdict.ERROR)
            self.assertTrue(r.failure_feedback)

    def test_changedfiles_valueerror_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "ok.py"
            script.write_text('print("ok")\n', encoding="utf-8")
            with patch("agents.review.verification.changedFiles",
                       side_effect=ValueError("git broken")):
                r = runReceipt({"cmd": f'python "{script}"', "expect": "exit_zero"},
                               tmp, {"ok": True}, authority=_contained_authority(tmp))
            self.assertIsNotNone(r)

    def test_changedfiles_typeerror_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "ok.py"
            script.write_text("pass\n", encoding="utf-8")
            with patch("agents.review.verification.changedFiles",
                       side_effect=TypeError("unexpected type")):
                r = runReceipt({"cmd": f'python "{script}"', "expect": "exit_zero"},
                               tmp, {"ok": True}, authority=_contained_authority(tmp))
            self.assertIsNotNone(r)

    def test_changedfiles_keyerror_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "ok.py"
            script.write_text("pass\n", encoding="utf-8")
            with patch("agents.review.verification.changedFiles",
                       side_effect=KeyError("missing")):
                r = runReceipt({"cmd": f'python "{script}"', "expect": "exit_zero"},
                               tmp, {"ok": True}, authority=_contained_authority(tmp))
            self.assertIsNotNone(r)

    def test_check_declared_targets_error_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "ok.py"
            script.write_text('print("ok")\n', encoding="utf-8")
            with patch("agents.review.verification._checkDeclaredTargets",
                       side_effect=KeyError("oops")):
                r = runReceipt({"cmd": f'python "{script}"', "expect": "exit_zero",
                                "targets": ["some/file.py"]},
                               tmp, {"ok": True}, authority=_contained_authority(tmp))
            self.assertIsNotNone(r)

    def test_cancel_check_returns_error_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "hang.py"
            script.write_text("import time; time.sleep(60)\n", encoding="utf-8")
            r = runReceipt({"cmd": f'python "{script}"', "expect": "exit_zero"},
                           tmp, {"ok": True}, cancel_check=lambda: True, timeout_seconds=30,
                           authority=_contained_authority(tmp))
            self.assertIs(r.verdict, Verdict.ERROR)
            self.assertIn("cancel", r.failure_feedback.lower())

def test_all_acceptance_vectors_are_embargoed_before_directory_or_process_side_effects():
    import pytest

    from agents.review import verification
    vectors = [["cmd", "/c", "claude"], ["powershell", "-Command", "claude"],
               ["wrapper.bat"], ["python", "-c", "print(1)"], ["renamed.exe"]]
    for argv in vectors:
        calls: list[object] = []
        with pytest.raises(verification.VerificationCommandRefused):
            verification._runVector(None, argv, "missing-dir")
        assert calls == []
