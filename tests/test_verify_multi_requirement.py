"""Regression test for the 'partial work passes a multi-requirement goal' bug.

A self-referential run once finished status=done 1/1 while delivering only 1 of 3
things its goal asked for: the brain-authored verify checked a single fact (file
runs / one token present), so a 2-of-3-missing subtask still PASSED.

R10 replaced the token-scan synthesizer (a goal word in a comment could pass it)
with DIFF-GROUNDED declared targets: the verify carries ``targets`` and the receipt
pipeline FAILS the subtask unless git shows a declared target actually changed.
This file locks: compound expects still assert EVERY needle, enumerated-requirement
extraction still powers decomposition, targets survive sanitization, and the plan
strengthener attaches diff-grounded targets to multi-requirement subtasks.
"""
from __future__ import annotations

import unittest

from agents import verifier

# The exact goal from the bug report.
GOAL = ("improve notifications/webdash.py with (1) auto-refresh meta tag, "
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
        reqs = verifier.extractRequirements(GOAL)
        self.assertEqual(len(reqs), 3, f"expected 3 requirements, got {reqs!r}")

    def test_no_requirements_for_plain_single_deliverable(self):
        self.assertEqual(verifier.extractRequirements("write a fibonacci function in fib.py"), [])

    def test_primary_target_file_found(self):
        self.assertEqual(verifier.primaryTargetFile(GOAL), "notifications/webdash.py")


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
        out = _strengthenPlanVerifies(GOAL, subs)
        self.assertTrue((out[0]["verify"] or {}).get("targets"),
                        "multi-requirement subtask must declare a diff-grounded target")

    def test_strengthener_skips_single_requirement_subtasks(self):
        from platform_core.orchestration.subtask import _strengthenPlanVerifies
        subs = [{"title": "unrelated docs pass", "description": "tidy the readme wording",
                 "verify": {"cmd": "python C:\\9to5\\x.py", "expect": "exit_zero"}}]
        out = _strengthenPlanVerifies(GOAL, subs)
        self.assertIsNone((out[0]["verify"] or {}).get("targets"))
