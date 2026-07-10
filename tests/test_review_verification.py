"""Unit tests for agents.review.verification -- silent-failure and type-coercion coverage.

Focused on: verdictFor pure-function edge cases, annotate/frozen-dataclass mutation,
VResult/receiptToVResult missing-key coercions, runReceipt executor_result coercion,
expect=None->str("None") coercion, diff-grounding exception swallowing, and empty
declared_targets fallthrough.
"""
from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from agents.review.verification import (
    Receipt,
    Verdict,
    VResult,
    VerifyCancelled,
    annotate,
    receiptToVResult,
    runReceipt,
    verdictFor,
)


# helpers

def _receipt(**kw):
    defaults = dict(
        verdict=Verdict.PASS, cmd=(), rc=0, expect_mode="exit_zero",
        matched=(), missing=(), diff_files=(), duration_s=0.0, failure_feedback="",
    )
    return Receipt(**{**defaults, **kw})


def _completed(rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(["python", "--version"], rc, stdout, stderr)


# verdictFor: rc type coercions

class TestVerdictForRcCoercions:
    def test_string_rc_zero_is_not_pass_for_exit_zero(self):
        """String rc '0' != int 0 -- must not silently become a passing exit."""
        verdict, _, _ = verdictFor("0", "", "exit_zero")
        assert verdict is Verdict.FAIL

    def test_int_zero_rc_passes_exit_zero(self):
        verdict, _, _ = verdictFor(0, "", "exit_zero")
        assert verdict is Verdict.PASS

    def test_nonzero_int_rc_fails_exit_zero(self):
        verdict, _, _ = verdictFor(1, "output", "exit_zero")
        assert verdict is Verdict.FAIL

    def test_none_rc_returns_error(self):
        verdict, _, _ = verdictFor(None, "", "exit_zero")
        assert verdict is Verdict.ERROR

    def test_nonzero_rc_fails_stdout_contains_even_when_needle_present(self):
        """rc != 0 must override a matching needle -- no silent PASS from output alone."""
        verdict, _, _ = verdictFor(1, "expected text here", "stdout_contains:expected text")
        assert verdict is Verdict.FAIL


# verdictFor: expect shape edge cases

class TestVerdictForExpectShapes:
    def test_none_expect_returns_error(self):
        verdict, _, _ = verdictFor(0, "output", None)
        assert verdict is Verdict.ERROR

    def test_empty_expect_returns_error(self):
        verdict, _, _ = verdictFor(0, "output", "")
        assert verdict is Verdict.ERROR

    def test_whitespace_only_expect_returns_error(self):
        verdict, _, _ = verdictFor(0, "output", "   ")
        assert verdict is Verdict.ERROR

    def test_unknown_shape_returns_error_not_pass(self):
        """Unknown expect shape must fail-closed -- never guess a passing verdict."""
        verdict, _, _ = verdictFor(0, "output", "unknown_shape:something")
        assert verdict is Verdict.ERROR

    def test_stdout_contains_needle_found(self):
        verdict, matched, _ = verdictFor(0, "hello world", "stdout_contains:hello")
        assert verdict is Verdict.PASS
        assert "hello" in matched

    def test_stdout_contains_needle_missing(self):
        verdict, _, missing = verdictFor(0, "goodbye", "stdout_contains:hello")
        assert verdict is Verdict.FAIL
        assert "hello" in missing

    def test_stdout_contains_empty_needle_degrades_to_exit_gate_pass(self):
        verdict, _, _ = verdictFor(0, "", "stdout_contains:")
        assert verdict is Verdict.PASS

    def test_stdout_contains_empty_needle_degrades_to_exit_gate_fail(self):
        verdict, _, _ = verdictFor(1, "text", "stdout_contains:")
        assert verdict is Verdict.FAIL

    def test_stdout_contains_all_partial_match_fails(self):
        verdict, matched, missing = verdictFor(0, "a b c", "stdout_contains_all:a||b||d")
        assert verdict is Verdict.FAIL
        assert "a" in matched and "b" in matched
        assert "d" in missing

    def test_stdout_contains_all_all_present_passes(self):
        verdict, matched, _ = verdictFor(0, "a b c d", "stdout_contains_all:a||b||d")
        assert verdict is Verdict.PASS

    def test_stdout_contains_all_empty_after_prefix_returns_error(self):
        verdict, _, _ = verdictFor(0, "anything", "stdout_contains_all:")
        assert verdict is Verdict.ERROR

    def test_stdout_regex_valid_match_passes(self):
        verdict, matched, _ = verdictFor(0, "Python 3.12.0", r"stdout_regex:Python \d+\.\d+")
        assert verdict is Verdict.PASS

    def test_stdout_regex_bad_pattern_returns_error(self):
        verdict, _, _ = verdictFor(0, "text", "stdout_regex:[invalid(")
        assert verdict is Verdict.ERROR

    def test_stdout_regex_empty_pattern_degrades_to_exit_gate(self):
        verdict, _, _ = verdictFor(0, "", "stdout_regex:")
        assert verdict is Verdict.PASS

    def test_stdout_regex_all_bad_pattern_returns_error(self):
        verdict, _, _ = verdictFor(0, "text", "stdout_regex_all:[bad(")
        assert verdict is Verdict.ERROR

    def test_stdout_regex_all_empty_after_prefix_returns_error(self):
        verdict, _, _ = verdictFor(0, "text", "stdout_regex_all:")
        assert verdict is Verdict.ERROR

    def test_stdout_regex_all_partial_miss_fails(self):
        verdict, _, missing = verdictFor(0, "hello", "stdout_regex_all:hello||world")
        assert verdict is Verdict.FAIL
        assert "world" in missing


# annotate: mutation of frozen dataclass

class TestAnnotate:
    def test_annotate_adds_key_to_receipt_annotations(self):
        r = _receipt()
        annotate(r, "extra", "value")
        assert r.annotations["extra"] == "value"

    def test_annotate_overwrites_existing_key(self):
        r = _receipt(annotations={"k": "old"})
        annotate(r, "k", "new")
        assert r.annotations["k"] == "new"

    def test_annotate_does_not_affect_other_receipt_fields(self):
        r = _receipt()
        annotate(r, "x", 1)
        assert r.verdict is Verdict.PASS and r.rc == 0

    def test_frozen_receipt_rejects_direct_field_assignment(self):
        r = _receipt()
        with pytest.raises((AttributeError, TypeError)):
            r.rc = 99


# VResult: missing-key silent coercions

class TestVResult:
    def test_passed_false_when_passed_key_missing(self):
        """Missing 'passed' key -> bool(None)=False -- silent wrong verdict."""
        r = _receipt()
        v = VResult(r, {})
        assert v.passed is False

    def test_passed_true_when_key_is_true(self):
        r = _receipt()
        v = VResult(r, {"passed": True})
        assert v.passed is True

    def test_passed_false_for_all_falsy_values(self):
        r = _receipt()
        for val in [0, None, "", False]:
            v = VResult(r, {"passed": val})
            assert v.passed is False

    def test_receipt_attribute_preserved(self):
        r = _receipt(verdict=Verdict.FAIL)
        v = VResult(r, {"passed": False})
        assert v.receipt is r

    def test_dict_access_works(self):
        r = _receipt()
        v = VResult(r, {"passed": True, "cmd": "pytest", "returncode": 0})
        assert v["cmd"] == "pytest"


# receiptToVResult: annotation coercions

class TestReceiptToVResult:
    def test_skipped_receipt_missing_executor_ok_reports_not_passed(self):
        """Missing executor_ok annotation -> bool(None)=False -> silent wrong passed=False."""
        r = _receipt(verdict=Verdict.SKIPPED, expect_mode="executor_exit_zero",
                     annotations={})
        v = receiptToVResult(r)
        assert v.passed is False

    def test_skipped_receipt_executor_ok_true_reports_passed(self):
        r = _receipt(verdict=Verdict.SKIPPED, expect_mode="executor_exit_zero",
                     annotations={"executor_ok": True, "stderr": ""})
        v = receiptToVResult(r)
        assert v.passed is True

    def test_pass_receipt_maps_passed_true(self):
        r = _receipt(verdict=Verdict.PASS, expect_mode="exit_zero", rc=0,
                     annotations={"cmd_str": "pytest", "expect_str": "exit_zero",
                                  "stdout": ".", "stderr": ""})
        v = receiptToVResult(r)
        assert v.passed is True

    def test_fail_receipt_maps_passed_false_with_stderr(self):
        r = _receipt(verdict=Verdict.FAIL, expect_mode="exit_zero", rc=1,
                     failure_feedback="rc=1",
                     annotations={"cmd_str": "pytest", "expect_str": "exit_zero",
                                  "stdout": "", "stderr": "FAILED"})
        v = receiptToVResult(r)
        assert v.passed is False
        assert v["stderr"] == "FAILED"

    def test_diff_grounded_failure_appends_feedback_to_stderr(self):
        r = _receipt(verdict=Verdict.FAIL, expect_mode="exit_zero", rc=0,
                     failure_feedback="no targets changed",
                     annotations={"cmd_str": "c", "expect_str": "exit_zero",
                                  "stdout": "", "stderr": "base",
                                  "diff_grounded": "failed"})
        v = receiptToVResult(r)
        assert "no targets changed" in v["stderr"]

    def test_error_verdict_maps_passed_false(self):
        r = _receipt(verdict=Verdict.ERROR, expect_mode="exit_zero", rc=-1,
                     annotations={"cmd_str": "bad", "expect_str": "exit_zero",
                                  "stdout": "", "stderr": "err"})
        v = receiptToVResult(r)
        assert v.passed is False


# runReceipt: executor_result type coercion

class TestRunReceiptExecutorCoercion:
    def _run_skipped(self, executor_result):
        with patch("agents.review.verification.sanitizeVerify", return_value=None), \
             patch("agents.review.verification.changedFiles", return_value=set()), \
             patch("agents.review.verification._checkDeclaredTargets",
                   return_value=(True, "")):
            return runReceipt(
                verify=None, work_dir="C:\\9to5", executor_result=executor_result
            )

    def test_string_executor_result_coerced_to_empty_dict(self):
        """String executor_result silently -> {} -> ok=None -> executor_ok=False."""
        receipt = self._run_skipped("not-a-dict")
        assert receipt.verdict is Verdict.SKIPPED
        assert not receipt.annotations.get("executor_ok")

    def test_none_executor_result_coerced_to_empty_dict(self):
        receipt = self._run_skipped(None)
        assert receipt.verdict is Verdict.SKIPPED

    def test_list_executor_result_coerced_to_empty_dict(self):
        receipt = self._run_skipped([{"ok": True}])
        assert not receipt.annotations.get("executor_ok")

    def test_dict_executor_result_ok_true_preserved(self):
        receipt = self._run_skipped({"ok": True, "returncode": 0})
        assert receipt.annotations.get("executor_ok") is True


# runReceipt: expect=None -> str("None") -> ERROR

class TestRunReceiptExpectNoneCoercion:
    def test_expect_none_from_sanitizer_errors(self):
        """sanitizeVerify returning expect=None -> str(None)='None' -> ERROR verdict."""
        completed = _completed(rc=0, stdout="Python 3.12\n")
        with patch("agents.review.verification.sanitizeVerify",
                   return_value={"cmd": "python --version", "expect": None}), \
             patch("agents.review.verification._runVector", return_value=completed), \
             patch("agents.review.verification.changedFiles", return_value=set()):
            receipt = runReceipt(
                verify={"cmd": "python --version", "expect": None},
                work_dir="C:\\9to5",
                executor_result={"ok": True},
            )
        assert receipt.verdict is Verdict.ERROR

    def test_verdictfor_string_none_is_error(self):
        """str(None)='None' does not match any documented expect shape -> ERROR."""
        verdict, _, _ = verdictFor(0, "output", "None")
        assert verdict is Verdict.ERROR


# runReceipt: diff-grounding exception -> silent PASS

class TestRunReceiptDiffGroundingSilentPass:
    def _run_with_grounding_exc(self, exc):
        completed = _completed(rc=0, stdout="ok\n")
        with patch("agents.review.verification.sanitizeVerify",
                   return_value={"cmd": "python --version", "expect": "exit_zero"}), \
             patch("agents.review.verification._runVector", return_value=completed), \
             patch("agents.review.verification.changedFiles", return_value={"file.py"}), \
             patch("agents.review.verification._checkDeclaredTargets", side_effect=exc):
            return runReceipt(
                verify={"cmd": "python --version", "expect": "exit_zero"},
                work_dir="C:\\9to5",
                executor_result={"ok": True},
                declared_targets=["file.py"],
            )

    def test_valueerror_swallowed_verdict_stays_pass(self):
        """ValueError from _checkDeclaredTargets swallowed -> grounded_ok=True -> PASS."""
        assert self._run_with_grounding_exc(ValueError("oops")).verdict is Verdict.PASS

    def test_typeerror_swallowed_verdict_stays_pass(self):
        assert self._run_with_grounding_exc(TypeError("bad")).verdict is Verdict.PASS

    def test_keyerror_swallowed_verdict_stays_pass(self):
        assert self._run_with_grounding_exc(KeyError("k")).verdict is Verdict.PASS


# runReceipt: empty declared_targets=[] fallthrough

class TestRunReceiptDeclaredTargetsFallthrough:
    def _run_spy(self, declared_targets, verify_targets):
        completed = _completed(rc=0, stdout="ok\n")
        verify_dict = {"cmd": "python --version", "expect": "exit_zero",
                       "targets": verify_targets}
        captured = {}

        def fake_check(work_dir, targets, cmd, changed):
            captured["targets"] = list(targets)
            return True, ""

        with patch("agents.review.verification.sanitizeVerify", return_value=verify_dict), \
             patch("agents.review.verification._runVector", return_value=completed), \
             patch("agents.review.verification.changedFiles",
                   return_value=set(verify_targets)), \
             patch("agents.review.verification._checkDeclaredTargets",
                   side_effect=fake_check):
            runReceipt(verify=verify_dict, work_dir="C:\\9to5",
                       executor_result={"ok": True},
                       declared_targets=declared_targets)
        return captured

    def test_empty_list_falls_through_to_verify_targets(self):
        """declared_targets=[] is falsy -> falls through to verify.get('targets')."""
        captured = self._run_spy([], ["surprise.py"])
        assert "surprise.py" in (captured.get("targets") or [])

    def test_none_falls_through_to_verify_targets(self):
        captured = self._run_spy(None, ["target.py"])
        assert "target.py" in (captured.get("targets") or [])

    def test_explicit_targets_override_verify_targets(self):
        captured = self._run_spy(["explicit.py"], ["other.py"])
        assert "explicit.py" in (captured.get("targets") or [])
        assert "other.py" not in (captured.get("targets") or [])


# runReceipt: cancellation and timeout

class TestRunReceiptCancellationAndTimeout:
    def test_verify_cancelled_returns_error_receipt(self):
        with patch("agents.review.verification.sanitizeVerify",
                   return_value={"cmd": "python --version", "expect": "exit_zero"}), \
             patch("agents.review.verification._runVector",
                   side_effect=VerifyCancelled("cancelled")):
            receipt = runReceipt(
                verify={"cmd": "python --version", "expect": "exit_zero"},
                work_dir="C:\\9to5", executor_result={"ok": True},
            )
        assert receipt.verdict is Verdict.ERROR
        assert "cancel" in receipt.failure_feedback.lower()

    def test_timeout_returns_error_receipt(self):
        with patch("agents.review.verification.sanitizeVerify",
                   return_value={"cmd": "python --version", "expect": "exit_zero"}), \
             patch("agents.review.verification._runVector",
                   side_effect=subprocess.TimeoutExpired(["python"], 30)):
            receipt = runReceipt(
                verify={"cmd": "python --version", "expect": "exit_zero"},
                work_dir="C:\\9to5", executor_result={"ok": True},
            )
        assert receipt.verdict is Verdict.ERROR
        assert "TIMEOUT" in receipt.failure_feedback


# runReceipt: cmd parse error

class TestRunReceiptCmdParseError:
    def test_unsplittable_cmd_returns_error_receipt(self):
        with patch("agents.review.verification.sanitizeVerify",
                   return_value={"cmd": "python --version", "expect": "exit_zero"}), \
             patch("agents.review.verification._splitCmd",
                   side_effect=ValueError("lex error")):
            receipt = runReceipt(
                verify={"cmd": "python --version", "expect": "exit_zero"},
                work_dir="C:\\9to5", executor_result={"ok": True},
            )
        assert receipt.verdict is Verdict.ERROR
        assert "parse error" in receipt.failure_feedback
