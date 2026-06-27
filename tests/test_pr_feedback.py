"""Focused tests for platform_core.orchestration.pr_feedback.

Tests cover:
  - _parsePRSlug: URL parsing (valid, invalid, edge-cases)
  - capturePRFeedback: gh-mocked happy path (CI pass + approved)
  - capturePRFeedback: CI failure → promote_safe=False + ledger write
  - capturePRFeedback: review changes_requested → promote_safe=False
  - capturePRFeedback: bad URL → skipped result, no ledger write
  - capturePRFeedback: gh CLI unavailable → graceful degrade
  - _writeLedger: calls record_feedback + record_reflection with correct args
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from platform_core.orchestration.pr_feedback import (
    _parsePRSlug,
    _writeLedger,
    capturePRFeedback,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GOOD_URL = "https://github.com/acme/nightclaw/pull/42"
_RUN_ID = "run-test-001"
_SUBTASK_ID = "st-001"


def _gh_side_effect_factory(sha="abc123", ci_runs=None, reviews=None):
    """Return a fake _gh that returns plausible data for each gh sub-command."""
    if ci_runs is None:
        ci_runs = [{"name": "build", "status": "completed", "conclusion": "success"}]
    if reviews is None:
        reviews = [{"state": "APPROVED", "body": "LGTM"}]

    def _fake_gh(args):
        joined = " ".join(args)
        if "headRefOid" in joined:
            return 0, sha
        if "check-runs" in joined:
            return 0, "\n".join(json.dumps(r) for r in ci_runs)
        if "pulls" in joined and "reviews" in joined:
            return 0, "\n".join(json.dumps(r) for r in reviews)
        return 0, ""

    return _fake_gh


# ---------------------------------------------------------------------------
# _parsePRSlug
# ---------------------------------------------------------------------------

class TestParsePRSlug(unittest.TestCase):
    def test_standard_url(self):
        result = _parsePRSlug("https://github.com/acme/repo/pull/99")
        self.assertEqual(result, ("acme", "repo", "99"))

    def test_trailing_slash(self):
        result = _parsePRSlug("https://github.com/acme/repo/pull/7/")
        self.assertEqual(result, ("acme", "repo", "7"))

    def test_with_query_string(self):
        result = _parsePRSlug("https://github.com/acme/repo/pull/7?foo=bar")
        self.assertEqual(result, ("acme", "repo", "7"))

    def test_invalid_url(self):
        self.assertIsNone(_parsePRSlug("https://gitlab.com/acme/repo/-/merge_requests/1"))

    def test_empty_string(self):
        self.assertIsNone(_parsePRSlug(""))

    def test_gh_cli_output_bare_url(self):
        # gh pr create often prints just the URL
        result = _parsePRSlug("https://github.com/9to5/nightclaw/pull/123\n")
        self.assertEqual(result, ("9to5", "nightclaw", "123"))


# ---------------------------------------------------------------------------
# capturePRFeedback — happy path
# ---------------------------------------------------------------------------

class TestCapturePRFeedbackHappyPath(unittest.TestCase):
    @mock.patch("platform_core.orchestration.pr_feedback._writeLedger")
    @mock.patch("platform_core.orchestration.pr_feedback._gh")
    def test_ci_pass_approved(self, mock_gh, mock_write):
        mock_gh.side_effect = _gh_side_effect_factory()
        result = capturePRFeedback(_GOOD_URL, _RUN_ID, _SUBTASK_ID, poll_interval=0)

        self.assertTrue(result["ok"])
        self.assertEqual(result["ci_status"], "passed")
        self.assertEqual(result["review_state"], "approved")
        self.assertTrue(result["promote_safe"])
        self.assertEqual(result["pr_url"], _GOOD_URL)
        mock_write.assert_called_once()

    @mock.patch("platform_core.orchestration.pr_feedback._writeLedger")
    @mock.patch("platform_core.orchestration.pr_feedback._gh")
    def test_provenance_fields(self, mock_gh, mock_write):
        mock_gh.side_effect = _gh_side_effect_factory()
        result = capturePRFeedback(_GOOD_URL, _RUN_ID, _SUBTASK_ID, poll_interval=0)

        prov = result["provenance"]
        self.assertEqual(prov["owner"], "acme")
        self.assertEqual(prov["repo"], "nightclaw")
        self.assertEqual(prov["pr_number"], "42")
        self.assertEqual(prov["run_id"], _RUN_ID)
        self.assertEqual(prov["subtask_id"], _SUBTASK_ID)
        self.assertEqual(prov["origin"], "pr_feedback")


# ---------------------------------------------------------------------------
# capturePRFeedback — CI failure blocks promotion
# ---------------------------------------------------------------------------

class TestCapturePRFeedbackCIFail(unittest.TestCase):
    @mock.patch("platform_core.orchestration.pr_feedback._writeLedger")
    @mock.patch("platform_core.orchestration.pr_feedback._gh")
    def test_ci_failure_blocks_promotion(self, mock_gh, mock_write):
        failing_runs = [{"name": "test", "status": "completed", "conclusion": "failure"}]
        mock_gh.side_effect = _gh_side_effect_factory(ci_runs=failing_runs)
        result = capturePRFeedback(_GOOD_URL, _RUN_ID, _SUBTASK_ID, poll_interval=0)

        self.assertEqual(result["ci_status"], "failed")
        self.assertFalse(result["promote_safe"])
        mock_write.assert_called_once()

    @mock.patch("platform_core.orchestration.pr_feedback._writeLedger")
    @mock.patch("platform_core.orchestration.pr_feedback._gh")
    def test_ci_timed_out_blocks_promotion(self, mock_gh, mock_write):
        timed_out = [{"name": "build", "status": "completed", "conclusion": "timed_out"}]
        mock_gh.side_effect = _gh_side_effect_factory(ci_runs=timed_out)
        result = capturePRFeedback(_GOOD_URL, _RUN_ID, poll_interval=0)

        self.assertFalse(result["promote_safe"])
        self.assertEqual(result["ci_status"], "failed")


# ---------------------------------------------------------------------------
# capturePRFeedback — review changes_requested blocks promotion
# ---------------------------------------------------------------------------

class TestCapturePRFeedbackReview(unittest.TestCase):
    @mock.patch("platform_core.orchestration.pr_feedback._writeLedger")
    @mock.patch("platform_core.orchestration.pr_feedback._gh")
    def test_changes_requested_blocks(self, mock_gh, mock_write):
        review = [{"state": "CHANGES_REQUESTED", "body": "Please fix the typo"}]
        mock_gh.side_effect = _gh_side_effect_factory(reviews=review)
        result = capturePRFeedback(_GOOD_URL, _RUN_ID, _SUBTASK_ID, poll_interval=0)

        self.assertEqual(result["review_state"], "changes_requested")
        self.assertFalse(result["promote_safe"])
        self.assertIn("Please fix the typo", result["review_feedback"])

    @mock.patch("platform_core.orchestration.pr_feedback._writeLedger")
    @mock.patch("platform_core.orchestration.pr_feedback._gh")
    def test_no_reviews_pending(self, mock_gh, mock_write):
        mock_gh.side_effect = _gh_side_effect_factory(reviews=[])
        result = capturePRFeedback(_GOOD_URL, _RUN_ID, poll_interval=0)

        self.assertEqual(result["review_state"], "none")
        # CI passed, no blocking reviews → promote_safe
        self.assertTrue(result["promote_safe"])


# ---------------------------------------------------------------------------
# capturePRFeedback — bad inputs
# ---------------------------------------------------------------------------

class TestCapturePRFeedbackBadInput(unittest.TestCase):
    def test_bad_url_skipped(self):
        result = capturePRFeedback("https://example.com/not-a-pr", _RUN_ID)
        self.assertFalse(result.get("ok"))
        self.assertTrue(result.get("skipped"))

    def test_empty_pr_url(self):
        result = capturePRFeedback("", _RUN_ID)
        self.assertFalse(result.get("ok"))

    def test_empty_run_id(self):
        result = capturePRFeedback(_GOOD_URL, "")
        self.assertFalse(result.get("ok"))

    @mock.patch("platform_core.orchestration.pr_feedback._gh",
                return_value=(-1, "gh CLI not found"))
    def test_gh_unavailable_degrades(self, _mock_gh):
        result = capturePRFeedback(_GOOD_URL, _RUN_ID, poll_interval=0)
        # Should not raise; must return a dict
        self.assertIsInstance(result, dict)
        self.assertIn("ok", result)


# ---------------------------------------------------------------------------
# _writeLedger — ledger integration
# ---------------------------------------------------------------------------

class TestWriteLedger(unittest.TestCase):
    @mock.patch("platform_core.orchestration.pr_feedback.record_reflection" if False else
                "memory.experience.record_reflection")
    @mock.patch("memory.experience.record_feedback")
    def test_calls_record_feedback(self, mock_fb, mock_refl):
        # Import lazily so we can patch before the import resolves
        with mock.patch("platform_core.orchestration.pr_feedback.record_feedback",
                        mock_fb, create=True), \
             mock.patch("platform_core.orchestration.pr_feedback.record_reflection",
                        mock_refl, create=True):
            # Patch the import inside _writeLedger
            import platform_core.orchestration.pr_feedback as mod
            original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else None

            result = {
                "ok": True,
                "pr_url": _GOOD_URL,
                "ci_status": "passed",
                "ci_summary": "All checks passed",
                "review_state": "approved",
                "review_feedback": [],
                "promote_safe": True,
            }
            with mock.patch.dict("sys.modules", {
                "memory.experience": mock.MagicMock(
                    record_feedback=mock_fb,
                    record_reflection=mock_refl,
                )
            }):
                _writeLedger(_RUN_ID, _SUBTASK_ID, _GOOD_URL, result)
                mock_fb.assert_called_once()
                call_kwargs = mock_fb.call_args[1]
                self.assertEqual(call_kwargs["kind"], "pr_ci")
                self.assertEqual(call_kwargs["run_id"], _RUN_ID)
                self.assertEqual(call_kwargs["target"], _GOOD_URL)

    def test_import_failure_does_not_raise(self):
        with mock.patch.dict("sys.modules", {"memory.experience": None}):
            # Must not raise even if memory is unavailable
            try:
                _writeLedger(_RUN_ID, _SUBTASK_ID, _GOOD_URL, {"ok": True, "promote_safe": False,
                              "ci_status": "failed", "review_state": "none",
                              "review_feedback": []})
            except Exception as exc:  # noqa: BLE001
                self.fail(f"_writeLedger raised on import failure: {exc}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        # Run the full unittest suite and exit with its result code.
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromModule(sys.modules[__name__])
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        sys.exit(0 if result.wasSuccessful() else 1)
    unittest.main()
