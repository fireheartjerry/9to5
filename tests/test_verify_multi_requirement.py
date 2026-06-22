"""Regression test for the 'partial work passes a multi-requirement goal' bug.

A self-referential run once finished status=done 1/1 while delivering only 1 of 3
things its goal asked for: the brain-authored verify checked a single fact (file
runs / one token present), so a 2-of-3-missing subtask still PASSED.

This locks the fix: when a goal enumerates N requirements, the verify must assert
ALL N -- a file with only requirement #1 done MUST fail verification, and a file
with all N done MUST pass. Pure-stdlib (``python -m unittest``); imports only the
dependency-light ``agents.verifier`` so it runs without ollama/discord installed.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agents import verifier

# The exact goal from the bug report.
GOAL = ("improve notifications/webdash.py with (1) auto-refresh meta tag, "
        "(2) elapsed-time line, (3) per-subtask green/red color coding.")

# webdash source with ONLY deliverable #1 (auto-refresh) -- the bug's partial state.
WEBDASH_ONLY_REFRESH = (
    '<!doctype html><html><head><meta charset="utf-8">\n'
    '<meta http-equiv="refresh" content="5">\n'
    '<title>9TO5</title></head><body>just the refresh tag</body></html>\n'
)

# webdash source with ALL THREE deliverables present.
WEBDASH_ALL_THREE = (
    '<!doctype html><html><head><meta charset="utf-8">\n'
    '<meta http-equiv="refresh" content="5">\n'
    '<title>9TO5</title></head><body>\n'
    '<div class="elapsed">elapsed: 00:03:11</div>\n'
    '<style>.ok{color:green}.bad{color:red}</style>\n'
    '</body></html>\n'
)

# Distinctive, AND-across-groups / OR-within-group markers for each requirement.
MARKER_GROUPS = [["refresh"], ["elapsed"], ["green", "red"]]


def _writeWebdash(tmp: str, body: str) -> str:
    p = Path(tmp) / "webdash.py"
    p.write_text(body, encoding="utf-8")
    return str(p)


class TestCompoundExpectation(unittest.TestCase):
    """The new stdout_contains_all / stdout_regex_all expectations check EVERY needle."""

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


class TestContentScanVerify(unittest.TestCase):
    """A compound content-scan verify built from explicit marker groups."""

    def test_fails_when_only_one_of_three_requirements_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = _writeWebdash(tmp, WEBDASH_ONLY_REFRESH)
            v = verifier.buildContentScanVerify(MARKER_GROUPS, target)
            self.assertTrue(verifier.isStrictVerify(v), "content-scan verify must be strict")
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertFalse(res["passed"], "2-of-3 missing must FAIL verification")

    def test_passes_when_all_three_requirements_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = _writeWebdash(tmp, WEBDASH_ALL_THREE)
            v = verifier.buildContentScanVerify(MARKER_GROUPS, target)
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            self.assertTrue(res["passed"], "all-3-present must PASS verification")

    def test_failure_output_names_the_missing_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = _writeWebdash(tmp, WEBDASH_ONLY_REFRESH)
            v = verifier.buildContentScanVerify(MARKER_GROUPS, target)
            res = verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})
            blob = (res.get("stdout") or "") + (res.get("stderr") or "")
            self.assertIn("elapsed", blob, "feedback should name the missing markers for retry")


class TestRequirementExtraction(unittest.TestCase):
    """Deterministic NL parsing that powers decomposition + compound-verify synthesis."""

    def test_extracts_three_enumerated_requirements(self):
        reqs = verifier.extractRequirements(GOAL)
        self.assertEqual(len(reqs), 3, f"expected 3 requirements, got {reqs!r}")

    def test_no_requirements_for_plain_single_deliverable(self):
        self.assertEqual(verifier.extractRequirements("write a fibonacci function in fib.py"), [])

    def test_markers_capture_distinctive_words(self):
        markers = verifier.requirementMarkers("auto-refresh meta tag")
        self.assertIn("refresh", markers)


class TestBuildRequirementsVerifyEndToEnd(unittest.TestCase):
    """The full synthesizer: goal text -> compound verify that fails on partial work."""

    def test_synthesized_verify_fails_on_partial_and_passes_on_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            partial = _writeWebdash(tmp, WEBDASH_ONLY_REFRESH)
            v = verifier.buildRequirementsVerify(GOAL, partial)
            self.assertIsNotNone(v, "an enumerated 3-part goal must yield a compound verify")
            self.assertFalse(
                verifier.runVerification(v, tmp, {"ok": True, "returncode": 0})["passed"])

            target = _writeWebdash(tmp, WEBDASH_ALL_THREE)
            v2 = verifier.buildRequirementsVerify(GOAL, target)
            self.assertTrue(
                verifier.runVerification(v2, tmp, {"ok": True, "returncode": 0})["passed"])

    def test_returns_none_for_single_deliverable_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = _writeWebdash(tmp, WEBDASH_ALL_THREE)
            self.assertIsNone(verifier.buildRequirementsVerify("tidy up webdash.py", target))

    def test_sanitize_keeps_compound_content_scan_and_strict_flag(self):
        # planning runs the strengthened verify through sanitizeVerify -- it must survive intact,
        # else the compound check is silently dropped back to 'executor exited 0'.
        v = verifier.buildContentScanVerify(MARKER_GROUPS, "/tmp/webdash.py")
        kept = verifier.sanitizeVerify(v)
        self.assertIsNotNone(kept)
        self.assertTrue(verifier.isStrictVerify(kept))


if __name__ == "__main__":
    unittest.main()
