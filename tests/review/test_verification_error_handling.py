"""Error-handling and edge-case tests for agents.review.verification.

Covers:
  verdictFor  -- all expect modes, type coercion, None rc, bad regex
  _splitCmd   -- windows paths, quoting
  _extractVerifyPath -- skip flags/known verbs, detect by extension/separator
  _normalizeWorkDir  -- path re-rooting logic
  VResult     -- dict shape, .passed, .receipt
  Receipt     -- .passed property, frozen immutability
  annotate    -- annotation mutation
  runReceipt  -- no-cmd/skipped, bad executor_result, cancel_check, spawn error
  receiptToVResult -- compat shim shape
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.review.verification import (
    Receipt,
    VResult,
    Verdict,
    annotate,
    receiptToVResult,
    runReceipt,
    verdictFor,
    _splitCmd,
    _extractVerifyPath,
    _normalizeWorkDir,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _receipt(verdict=Verdict.PASS, rc=0, expect_mode="exit_zero",
             matched=(), missing=(), diff_files=(), duration_s=0.0,
             failure_feedback="", cmd=(), **kw) -> Receipt:
    annotations = kw.pop("annotations", {})
    return Receipt(
        verdict=verdict, cmd=cmd, rc=rc, expect_mode=expect_mode,
        matched=matched, missing=missing, diff_files=diff_files,
        duration_s=duration_s, failure_feedback=failure_feedback,
        annotations=annotations,
    )


# ---------------------------------------------------------------------------
# verdictFor -- type coercion
# ---------------------------------------------------------------------------

class TestVerdictForTypeCoercion(unittest.TestCase):
    """Non-string / empty / None expect => ERROR; None rc => ERROR."""

    def test_none_expect_is_error(self):
        v, m, s = verdictFor(0, "anything", None)
        self.assertIs(v, Verdict.ERROR)
        self.assertEqual(m, ())
        self.assertEqual(s, ())

    def test_int_expect_is_error(self):
        v, _, _ = verdictFor(0, "ok", 42)
        self.assertIs(v, Verdict.ERROR)

    def test_list_expect_is_error(self):
        v, _, _ = verdictFor(0, "ok", ["exit_zero"])
        self.assertIs(v, Verdict.ERROR)

    def test_empty_string_expect_is_error(self):
        v, _, _ = verdictFor(0, "ok", "")
        self.assertIs(v, Verdict.ERROR)

    def test_whitespace_only_expect_is_error(self):
        v, _, _ = verdictFor(0, "ok", "   ")
        self.assertIs(v, Verdict.ERROR)

    def test_none_rc_is_error(self):
        v, _, _ = verdictFor(None, "ok", "exit_zero")
        self.assertIs(v, Verdict.ERROR)

    def test_unknown_expect_shape_is_error(self):
        v, _, _ = verdictFor(0, "ok", "magic_check:foo")
        self.assertIs(v, Verdict.ERROR)

    def test_none_output_treated_as_empty(self):
        # output=None must not crash -- coerced to ""
        v, _, missing = verdictFor(0, None, "stdout_contains:needle")
        self.assertIs(v, Verdict.FAIL)
        self.assertIn("needle", missing)


# ---------------------------------------------------------------------------
# verdictFor -- exit_zero
# ---------------------------------------------------------------------------

class TestVerdictForExitZero(unittest.TestCase):
    def test_pass_on_rc_zero(self):
        v, m, s = verdictFor(0, "", "exit_zero")
        self.assertIs(v, Verdict.PASS)
        self.assertEqual(m, ())
        self.assertEqual(s, ())

    def test_fail_on_rc_nonzero(self):
        self.assertIs(verdictFor(1, "", "exit_zero")[0], Verdict.FAIL)

    def test_fail_on_rc_negative(self):
        self.assertIs(verdictFor(-1, "", "exit_zero")[0], Verdict.FAIL)


# ---------------------------------------------------------------------------
# verdictFor -- stdout_contains
# ---------------------------------------------------------------------------

class TestVerdictForStdoutContains(unittest.TestCase):
    def test_pass_when_needle_in_output_rc_zero(self):
        v, matched, missing = verdictFor(0, "hello world", "stdout_contains:hello")
        self.assertIs(v, Verdict.PASS)
        self.assertIn("hello", matched)
        self.assertEqual(missing, ())

    def test_fail_when_needle_missing(self):
        v, matched, missing = verdictFor(0, "hello world", "stdout_contains:NOPE")
        self.assertIs(v, Verdict.FAIL)
        self.assertIn("NOPE", missing)
        self.assertEqual(matched, ())

    def test_fail_when_rc_nonzero_even_if_needle_present(self):
        v, _, _ = verdictFor(1, "hello", "stdout_contains:hello")
        self.assertIs(v, Verdict.FAIL)

    def test_empty_needle_falls_back_to_exit_gate_pass(self):
        # FX-2: empty needle => exit_zero gate
        self.assertIs(verdictFor(0, "", "stdout_contains:")[0], Verdict.PASS)

    def test_empty_needle_fails_on_nonzero_rc(self):
        self.assertIs(verdictFor(1, "", "stdout_contains:")[0], Verdict.FAIL)


# ---------------------------------------------------------------------------
# verdictFor -- stdout_regex
# ---------------------------------------------------------------------------

class TestVerdictForStdoutRegex(unittest.TestCase):
    def test_pass_on_match(self):
        v, matched, _ = verdictFor(0, "error: 42 found", r"stdout_regex:error: \d+")
        self.assertIs(v, Verdict.PASS)
        self.assertIn(r"error: \d+", matched)

    def test_fail_when_no_match(self):
        v, _, _ = verdictFor(0, "no errors", r"stdout_regex:error: \d+")
        self.assertIs(v, Verdict.FAIL)

    def test_bad_regex_is_error(self):
        v, _, _ = verdictFor(0, "anything", "stdout_regex:[invalid")
        self.assertIs(v, Verdict.ERROR)

    def test_empty_pattern_falls_back_to_exit_gate(self):
        self.assertIs(verdictFor(0, "", "stdout_regex:")[0], Verdict.PASS)

    def test_fail_on_rc_nonzero_even_if_pattern_matches(self):
        v, _, _ = verdictFor(1, "MARKER", "stdout_regex:MARKER")
        self.assertIs(v, Verdict.FAIL)


# ---------------------------------------------------------------------------
# verdictFor -- compound *_all
# ---------------------------------------------------------------------------

class TestVerdictForCompoundAll(unittest.TestCase):
    def test_contains_all_all_present(self):
        v, matched, missing = verdictFor(0, "foo bar baz", "stdout_contains_all:foo||bar||baz")
        self.assertIs(v, Verdict.PASS)
        self.assertEqual(set(matched), {"foo", "bar", "baz"})
        self.assertEqual(missing, ())

    def test_contains_all_some_missing(self):
        v, matched, missing = verdictFor(0, "foo", "stdout_contains_all:foo||MISSING")
        self.assertIs(v, Verdict.FAIL)
        self.assertIn("MISSING", missing)
        self.assertIn("foo", matched)

    def test_contains_all_empty_needles_is_error(self):
        v, _, _ = verdictFor(0, "anything", "stdout_contains_all:")
        self.assertIs(v, Verdict.ERROR)

    def test_contains_all_fails_on_nonzero_rc(self):
        v, _, _ = verdictFor(1, "foo bar", "stdout_contains_all:foo||bar")
        self.assertIs(v, Verdict.FAIL)

    def test_regex_all_empty_is_error(self):
        v, _, _ = verdictFor(0, "ok", "stdout_regex_all:")
        self.assertIs(v, Verdict.ERROR)

    def test_regex_all_bad_pattern_is_error(self):
        v, _, _ = verdictFor(0, "ok", "stdout_regex_all:[bad")
        self.assertIs(v, Verdict.ERROR)

    def test_regex_all_all_match(self):
        v, matched, missing = verdictFor(0, "abc 123", r"stdout_regex_all:\d+||\w+")
        self.assertIs(v, Verdict.PASS)
        self.assertEqual(missing, ())


# ---------------------------------------------------------------------------
# _splitCmd
# ---------------------------------------------------------------------------

class TestSplitCmd(unittest.TestCase):
    def test_simple_command(self):
        self.assertEqual(_splitCmd("python foo.py"), ["python", "foo.py"])

    def test_double_quoted_path(self):
        result = _splitCmd('python "C:\\path\\to file\\script.py"')
        self.assertEqual(result, ["python", "C:\\path\\to file\\script.py"])

    def test_single_quoted_arg(self):
        result = _splitCmd("echo 'hello world'")
        self.assertEqual(result, ["echo", "hello world"])

    def test_windows_backslash_path_unquoted(self):
        result = _splitCmd("python C:\\9to5\\tests\\test_foo.py")
        self.assertIn("C:\\9to5\\tests\\test_foo.py", result)

    def test_multiple_flags(self):
        result = _splitCmd("pytest -n auto -q tests/foo.py")
        self.assertEqual(result, ["pytest", "-n", "auto", "-q", "tests/foo.py"])

    def test_empty_string(self):
        self.assertEqual(_splitCmd(""), [])


# ---------------------------------------------------------------------------
# _extractVerifyPath
# ---------------------------------------------------------------------------

class TestExtractVerifyPath(unittest.TestCase):
    def test_py_extension(self):
        self.assertEqual(_extractVerifyPath("python tests/test_foo.py"), "tests/test_foo.py")

    def test_skips_known_verbs(self):
        self.assertEqual(_extractVerifyPath("python -m pytest tests/test_foo.py"), "tests/test_foo.py")

    def test_skips_flags(self):
        self.assertEqual(_extractVerifyPath("pytest -n auto tests/bar.py"), "tests/bar.py")

    def test_forward_slash_path(self):
        self.assertEqual(_extractVerifyPath("python some/path/here"), "some/path/here")

    def test_backslash_path(self):
        result = _extractVerifyPath("python C:\\some\\path")
        self.assertEqual(result, "C:\\some\\path")

    def test_returns_none_for_no_path_like_token(self):
        self.assertIsNone(_extractVerifyPath("pytest"))

    def test_single_token_returns_none(self):
        # First token (the command itself) is always skipped
        self.assertIsNone(_extractVerifyPath("tests/foo.py"))

    def test_flag_only_args_return_none(self):
        self.assertIsNone(_extractVerifyPath("pytest -v -s"))


# ---------------------------------------------------------------------------
# _normalizeWorkDir
# ---------------------------------------------------------------------------

class TestNormalizeWorkDir(unittest.TestCase):
    def test_no_path_candidate_returns_work_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _normalizeWorkDir("pytest", tmp)
            self.assertEqual(result, tmp)

    def test_relative_path_in_project_root_rerooters(self):
        with tempfile.TemporaryDirectory() as proj_tmp:
            with tempfile.TemporaryDirectory() as work_tmp:
                test_dir = Path(proj_tmp) / "tests"
                test_dir.mkdir()
                (test_dir / "test_foo.py").write_text("", encoding="utf-8")
                with patch("agents.review.verification.config") as mock_cfg:
                    mock_cfg.PROJECT_ROOT = proj_tmp
                    mock_cfg.INSTALL_ROOT = "/nonexistent/path/xyz"
                    result = _normalizeWorkDir("python tests/test_foo.py", work_tmp)
                    self.assertEqual(result, proj_tmp)

    def test_path_in_work_dir_uses_work_dir(self):
        with tempfile.TemporaryDirectory() as work_tmp:
            with tempfile.TemporaryDirectory() as proj_tmp:
                test_dir = Path(work_tmp) / "tests"
                test_dir.mkdir()
                (test_dir / "local.py").write_text("", encoding="utf-8")
                with patch("agents.review.verification.config") as mock_cfg:
                    mock_cfg.PROJECT_ROOT = proj_tmp
                    mock_cfg.INSTALL_ROOT = "/nonexistent/path/xyz"
                    result = _normalizeWorkDir("python tests/local.py", work_tmp)
                    self.assertEqual(result, work_tmp)


# ---------------------------------------------------------------------------
# VResult
# ---------------------------------------------------------------------------

class TestVResult(unittest.TestCase):
    def _vr(self, passed: bool, **extra) -> VResult:
        r = _receipt(Verdict.PASS if passed else Verdict.FAIL, rc=0 if passed else 1)
        mapping = {"passed": passed, "cmd": "x", "expect": "exit_zero",
                   "returncode": 0, "stdout": "", "stderr": ""}
        mapping.update(extra)
        return VResult(r, mapping)

    def test_passed_true(self):
        self.assertTrue(self._vr(True).passed)

    def test_passed_false(self):
        self.assertFalse(self._vr(False).passed)

    def test_receipt_attribute(self):
        r = _receipt()
        vr = VResult(r, {"passed": True})
        self.assertIs(vr.receipt, r)
    def test_dict_access_works(self):
        vr = self._vr(True)
        self.assertEqual(vr["returncode"], 0)
        self.assertEqual(vr["stdout"], "")

    def test_passed_truthy_int(self):
        r = _receipt()
        vr = VResult(r, {"passed": 1})
        self.assertTrue(vr.passed)

    def test_passed_absent_key_is_false(self):
        r = _receipt()
        vr = VResult(r, {})
        self.assertFalse(vr.passed)


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------

class TestReceipt(unittest.TestCase):
    def test_passed_true_for_pass(self):
        self.assertTrue(_receipt(Verdict.PASS).passed)

    def test_passed_false_for_fail(self):
        self.assertFalse(_receipt(Verdict.FAIL).passed)

    def test_passed_false_for_error(self):
        self.assertFalse(_receipt(Verdict.ERROR).passed)

    def test_passed_false_for_skipped(self):
        self.assertFalse(_receipt(Verdict.SKIPPED).passed)

    def test_frozen_cannot_set_attribute(self):
        r = _receipt()
        with self.assertRaises((AttributeError, TypeError)):
            r.verdict = Verdict.FAIL  # type: ignore[misc]

    def test_annotations_default_is_empty_dict(self):
        r = _receipt()
        self.assertEqual(r.annotations, {})


# ---------------------------------------------------------------------------
# annotate
# ---------------------------------------------------------------------------

class TestAnnotate(unittest.TestCase):
    def test_adds_key(self):
        r = _receipt()
        annotate(r, "my_key", "my_value")
        self.assertEqual(r.annotations["my_key"], "my_value")

    def test_overwrites_existing(self):
        r = _receipt()
        annotate(r, "k", "v1")
        annotate(r, "k", "v2")
        self.assertEqual(r.annotations["k"], "v2")

    def test_accepts_complex_value(self):
        r = _receipt()
        annotate(r, "data", {"nested": [1, 2]})
        self.assertEqual(r.annotations["data"], {"nested": [1, 2]})

    def test_multiple_keys(self):
        r = _receipt()
        annotate(r, "a", 1)
        annotate(r, "b", 2)
        self.assertEqual(r.annotations["a"], 1)
        self.assertEqual(r.annotations["b"], 2)


# ---------------------------------------------------------------------------
# runReceipt -- skipped / no-cmd paths
# ---------------------------------------------------------------------------

class TestRunReceiptSkippedPath(unittest.TestCase):
    def test_none_verify_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = runReceipt(None, tmp, {"ok": True, "returncode": 0})
            self.assertIs(r.verdict, Verdict.SKIPPED)
            self.assertEqual(r.cmd, ())

    def test_verify_with_no_cmd_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = runReceipt({"expect": "exit_zero"}, tmp, {"ok": True, "returncode": 0})
            self.assertIs(r.verdict, Verdict.SKIPPED)

    def test_non_dict_executor_result_no_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = runReceipt(None, tmp, "not-a-dict")
            self.assertIs(r.verdict, Verdict.SKIPPED)

    def test_none_executor_result_no_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = runReceipt(None, tmp, None)
            self.assertIs(r.verdict, Verdict.SKIPPED)

    def test_empty_dict_executor_result_no_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = runReceipt(None, tmp, {})
            self.assertIs(r.verdict, Verdict.SKIPPED)


# ---------------------------------------------------------------------------
# runReceipt -- error paths (spawn failure, cancel)
# ---------------------------------------------------------------------------

class TestRunReceiptErrorPaths(unittest.TestCase):
    def test_spawn_error_returns_error_receipt(self):
        """Unresolvable command => ERROR receipt, no uncaught exception."""
        with tempfile.TemporaryDirectory() as tmp:
            v = {"cmd": "no_such_exe_xyz_abc_99 --flag", "expect": "exit_zero"}
            r = runReceipt(v, tmp, {"ok": True})
            self.assertIs(r.verdict, Verdict.ERROR)
            self.assertIn("error", r.failure_feedback.lower())

    def test_cancel_check_returns_error_receipt(self):
        """cancel_check that fires immediately => ERROR receipt within <1 s."""
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "hang.py"
            script.write_text("import time; time.sleep(60)\n", encoding="utf-8")
            v = {"cmd": f'python "{script}"', "expect": "exit_zero"}

            r = runReceipt(v, tmp, {"ok": True}, cancel_check=lambda: True, timeout_seconds=30)
            self.assertIs(r.verdict, Verdict.ERROR)
            self.assertIn("cancel", r.failure_feedback.lower())


# ---------------------------------------------------------------------------
# receiptToVResult
# ---------------------------------------------------------------------------

class TestReceiptToVResult(unittest.TestCase):
    def test_skipped_executor_ok_passes(self):
        r = _receipt(Verdict.SKIPPED, rc=0, expect_mode="executor_exit_zero",
                     annotations={"stdout": "", "stderr": "", "executor_ok": True})
        vr = receiptToVResult(r)
        self.assertTrue(vr["passed"])
        self.assertIsNone(vr["cmd"])

    def test_skipped_executor_not_ok_fails(self):
        r = _receipt(Verdict.SKIPPED, rc=1, expect_mode="executor_exit_zero",
                     annotations={"stdout": "", "stderr": "crash", "executor_ok": False})
        vr = receiptToVResult(r)
        self.assertFalse(vr["passed"])

    def test_pass_receipt_returns_passed_true(self):
        r = _receipt(Verdict.PASS, rc=0, expect_mode="exit_zero",
                     cmd=("python", "t.py"), duration_s=0.01,
                     annotations={"stdout": "ok", "stderr": "",
                                  "cmd_str": "python t.py", "expect_str": "exit_zero"})
        vr = receiptToVResult(r)
        self.assertTrue(vr["passed"])
        self.assertEqual(vr["stdout"], "ok")

    def test_fail_receipt_returns_passed_false(self):
        r = _receipt(Verdict.FAIL, rc=1, expect_mode="exit_zero",
                     cmd=("python", "t.py"), failure_feedback="exit rc=1",
                     annotations={"stdout": "", "stderr": "err",
                                  "cmd_str": "python t.py", "expect_str": "exit_zero"})
        vr = receiptToVResult(r)
        self.assertFalse(vr["passed"])
        self.assertEqual(vr["returncode"], 1)

    def test_vresult_has_receipt_attribute(self):
        r = _receipt(Verdict.PASS, rc=0, expect_mode="exit_zero",
                     annotations={"stdout": "", "stderr": "",
                                  "cmd_str": "x", "expect_str": "exit_zero"})
        vr = receiptToVResult(r)
        self.assertIs(vr.receipt, r)
