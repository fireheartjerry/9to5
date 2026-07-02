"""Acceptance test: learning loop captures PR feedback via record_pr_outcome.

Run directly (acceptance gate):
    python tests/test_learning_loop.py
    # expects stdout to contain: PR feedback captured successfully

Run via pytest:
    python -m pytest tests/test_learning_loop.py -v
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

from platform_core.orchestration.pr_feedback import capturePRFeedback, _writeLedger

_GOOD_URL = "https://github.com/acme/nightclaw/pull/7"
_RUN_ID = "run-learning-loop-001"
_SUBTASK_ID = "st-learning-001"


def _make_gh(sha="deadbeef",
             ci_runs=None,
             reviews=None):
    if ci_runs is None:
        ci_runs = [{"name": "ci", "status": "completed", "conclusion": "success"}]
    if reviews is None:
        reviews = [{"state": "APPROVED", "body": "looks good"}]

    def _fake(args):
        joined = " ".join(args)
        if "headRefOid" in joined:
            return 0, sha
        if "check-runs" in joined:
            return 0, "\n".join(json.dumps(r) for r in ci_runs)
        if "pulls" in joined and "reviews" in joined:
            return 0, "\n".join(json.dumps(r) for r in reviews)
        return 0, ""

    return _fake


class TestLearningLoopPRFeedbackCapture(unittest.TestCase):
    """Verify that capturePRFeedback triggers record_pr_outcome in the learning loop."""

    @mock.patch("platform_core.orchestration.pr_feedback._gh")
    def test_record_pr_outcome_called_on_success(self, mock_gh):
        mock_gh.side_effect = _make_gh()
        with mock.patch("platform_core.orchestration.pr_feedback.record_pr_outcome",
                        create=True) as mock_rec_pr:
            # Patch the lazy import inside _writeLedger
            with mock.patch.dict("sys.modules", {
                "memory.experience": mock.MagicMock(
                    record_feedback=mock.MagicMock(),
                    record_reflection=mock.MagicMock(),
                ),
                "memory.experience_pr": mock.MagicMock(
                    record_pr_outcome=mock_rec_pr,
                ),
            }):
                result = capturePRFeedback(
                    _GOOD_URL, _RUN_ID, _SUBTASK_ID, poll_interval=0
                )

        self.assertTrue(result.get("ok"), f"capturePRFeedback failed: {result}")
        self.assertEqual(result["ci_status"], "passed")
        self.assertTrue(result["promote_safe"])

    @mock.patch("platform_core.orchestration.pr_feedback._gh")
    def test_record_pr_outcome_called_on_ci_failure(self, mock_gh):
        failing = [{"name": "tests", "status": "completed", "conclusion": "failure"}]
        mock_gh.side_effect = _make_gh(ci_runs=failing)
        captured: list[dict] = []

        def _fake_record(run_id, pr_url, result, *, subtask_id=None, db_path=None):
            captured.append({"run_id": run_id, "pr_url": pr_url,
                             "result": result, "subtask_id": subtask_id})
            return True

        with mock.patch.dict("sys.modules", {
            "memory.experience": mock.MagicMock(
                record_feedback=mock.MagicMock(),
                record_reflection=mock.MagicMock(),
            ),
            "memory.experience_pr": mock.MagicMock(record_pr_outcome=_fake_record),
        }):
            result = capturePRFeedback(
                _GOOD_URL, _RUN_ID, _SUBTASK_ID, poll_interval=0
            )

        self.assertFalse(result["promote_safe"])
        self.assertEqual(result["ci_status"], "failed")
        self.assertEqual(len(captured), 1)
        rec = captured[0]
        self.assertEqual(rec["run_id"], _RUN_ID)
        self.assertEqual(rec["pr_url"], _GOOD_URL)
        self.assertEqual(rec["subtask_id"], _SUBTASK_ID)
        self.assertFalse(rec["result"]["promote_safe"])

    def test_writeLedger_calls_record_pr_outcome_with_provenance(self):
        called: list[dict] = []

        def _fake_record(run_id, pr_url, result, *, subtask_id=None, db_path=None):
            called.append({"run_id": run_id, "pr_url": pr_url,
                           "result": result, "subtask_id": subtask_id})
            return True

        payload = {
            "ok": True,
            "pr_url": _GOOD_URL,
            "ci_status": "passed",
            "ci_summary": "All checks passed",
            "review_state": "approved",
            "review_feedback": [],
            "promote_safe": True,
            "provenance": {"origin": "pr_feedback", "run_id": _RUN_ID},
        }
        with mock.patch.dict("sys.modules", {
            "memory.experience": mock.MagicMock(
                record_feedback=mock.MagicMock(),
                record_reflection=mock.MagicMock(),
            ),
            "memory.experience_pr": mock.MagicMock(record_pr_outcome=_fake_record),
        }):
            _writeLedger(_RUN_ID, _SUBTASK_ID, _GOOD_URL, payload)

        self.assertEqual(len(called), 1)
        rec = called[0]
        self.assertEqual(rec["run_id"], _RUN_ID)
        self.assertEqual(rec["pr_url"], _GOOD_URL)
        self.assertEqual(rec["subtask_id"], _SUBTASK_ID)
        self.assertTrue(rec["result"]["promote_safe"])

    def test_writeLedger_record_pr_outcome_failure_does_not_raise(self):
        def _boom(*args, **kwargs):
            raise RuntimeError("db down")

        with mock.patch.dict("sys.modules", {
            "memory.experience": mock.MagicMock(
                record_feedback=mock.MagicMock(),
                record_reflection=mock.MagicMock(),
            ),
            "memory.experience_pr": mock.MagicMock(record_pr_outcome=_boom),
        }):
            try:
                _writeLedger(_RUN_ID, _SUBTASK_ID, _GOOD_URL, {
                    "ok": True, "promote_safe": False,
                    "ci_status": "failed", "review_state": "none",
                    "review_feedback": [],
                })
            except Exception as exc:
                self.fail(f"_writeLedger raised on record_pr_outcome failure: {exc}")
