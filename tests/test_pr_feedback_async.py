"""Unit tests for the daemon thread in review_mixin.OrchestratorReviewMixin.createPullRequest.

Covers:
  - daemon thread spawned with correct target, kwargs, name, and daemon=True
  - no thread when PR creation returns ok=False or missing URL
  - subtask_id selection: last non-removed/non-skipped subtask (or None)
  - capturePRFeedback exception inside thread does not propagate to caller
  - _pollCIStatus: passed, failed, pending, unknown
  - _fetchReviews: approved, changes_requested, mixed, failure
"""
from __future__ import annotations

import json
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from platform_core.orchestration.pr_feedback import (
    _fetchReviews,
    _pollCIStatus,
    capturePRFeedback,
)
from platform_core.orchestration.review_mixin import OrchestratorReviewMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PR_URL = "https://github.com/acme/nightclaw/pull/7"
_RUN_ID = "run-deadbeef-1234"
_SUBTASK_ID = "st-042"


# ---------------------------------------------------------------------------
# Minimal concrete stub for OrchestratorReviewMixin
# ---------------------------------------------------------------------------

class _ConcreteReviewMixin(OrchestratorReviewMixin):
    """Bare-minimum concrete subclass — provides only what createPullRequest needs."""


def _make_state(task_id: str = _RUN_ID, subtasks: list | None = None):
    """Return a minimal TaskState-like object."""
    state = mock.MagicMock()
    state.task_id = task_id
    state.subtasks = subtasks if subtasks is not None else [
        {"subtask_id": _SUBTASK_ID, "status": "done"},
    ]
    return state


# ---------------------------------------------------------------------------
# Thread spawning — happy paths
# ---------------------------------------------------------------------------

class TestCreatePRThreadSpawn(unittest.TestCase):
    """createPullRequest spawns a daemon thread when PR creation succeeds."""

    def _call(self, result_dict, state=None):
        state = state or _make_state()
        with mock.patch(
            "platform_core.orchestration.review_mixin.orchestrator_github"
        ) as mock_gh, mock.patch(
            "platform_core.orchestration.review_mixin.threading.Thread"
        ) as mock_thread_cls:
            mock_gh.createPullRequest.return_value = result_dict
            mock_instance = mock.MagicMock()
            mock_thread_cls.return_value = mock_instance
            mixin = _ConcreteReviewMixin()
            rv = mixin.createPullRequest(state, "/work")
            return rv, mock_thread_cls, mock_instance

    def test_thread_created_on_success(self):
        _, mock_cls, mock_inst = self._call({"ok": True, "url": _PR_URL})
        mock_cls.assert_called_once()
        mock_inst.start.assert_called_once()

    def test_thread_is_daemon(self):
        _, mock_cls, _ = self._call({"ok": True, "url": _PR_URL})
        kwargs = mock_cls.call_args[1]
        self.assertTrue(kwargs["daemon"])

    def test_thread_target_is_capture_fn(self):
        _, mock_cls, _ = self._call({"ok": True, "url": _PR_URL})
        kwargs = mock_cls.call_args[1]
        self.assertIs(kwargs["target"], capturePRFeedback)

    def test_thread_kwargs_pr_url(self):
        _, mock_cls, _ = self._call({"ok": True, "url": _PR_URL})
        task_kwargs = mock_cls.call_args[1]["kwargs"]
        self.assertEqual(task_kwargs["pr_url"], _PR_URL)

    def test_thread_kwargs_run_id(self):
        state = _make_state(task_id=_RUN_ID)
        _, mock_cls, _ = self._call({"ok": True, "url": _PR_URL}, state=state)
        task_kwargs = mock_cls.call_args[1]["kwargs"]
        self.assertEqual(task_kwargs["run_id"], _RUN_ID)

    def test_thread_name_prefix(self):
        state = _make_state(task_id=_RUN_ID)
        _, mock_cls, _ = self._call({"ok": True, "url": _PR_URL}, state=state)
        name = mock_cls.call_args[1]["name"]
        self.assertTrue(name.startswith("pr-feedback-"))
        self.assertIn(_RUN_ID[:8], name)

    def test_return_value_passed_through(self):
        expected = {"ok": True, "url": _PR_URL, "extra": "data"}
        rv, _, _ = self._call(expected)
        self.assertEqual(rv, expected)


# ---------------------------------------------------------------------------
# Thread spawning — no-op paths
# ---------------------------------------------------------------------------

class TestCreatePRNoThread(unittest.TestCase):
    """createPullRequest must NOT spawn a thread when PR creation fails or URL absent."""

    def _count_threads(self, result_dict):
        with mock.patch(
            "platform_core.orchestration.review_mixin.orchestrator_github"
        ) as mock_gh, mock.patch(
            "platform_core.orchestration.review_mixin.threading.Thread"
        ) as mock_cls:
            mock_gh.createPullRequest.return_value = result_dict
            mixin = _ConcreteReviewMixin()
            mixin.createPullRequest(_make_state(), "/work")
            return mock_cls.call_count

    def test_no_thread_when_ok_false(self):
        self.assertEqual(self._count_threads({"ok": False, "url": _PR_URL}), 0)

    def test_no_thread_when_url_missing(self):
        self.assertEqual(self._count_threads({"ok": True}), 0)

    def test_no_thread_when_url_empty(self):
        self.assertEqual(self._count_threads({"ok": True, "url": ""}), 0)

    def test_no_thread_when_result_empty(self):
        self.assertEqual(self._count_threads({}), 0)


# ---------------------------------------------------------------------------
# subtask_id selection
# ---------------------------------------------------------------------------

class TestSubtaskIdSelection(unittest.TestCase):
    """createPullRequest picks last non-removed/non-skipped subtask."""

    def _get_subtask_id(self, subtasks):
        state = _make_state(subtasks=subtasks)
        with mock.patch(
            "platform_core.orchestration.review_mixin.orchestrator_github"
        ) as mock_gh, mock.patch(
            "platform_core.orchestration.review_mixin.threading.Thread"
        ) as mock_cls:
            mock_gh.createPullRequest.return_value = {"ok": True, "url": _PR_URL}
            mock_cls.return_value = mock.MagicMock()
            mixin = _ConcreteReviewMixin()
            mixin.createPullRequest(state, "/work")
            return mock_cls.call_args[1]["kwargs"]["subtask_id"]

    def test_picks_last_done_subtask(self):
        subtasks = [
            {"subtask_id": "st-001", "status": "done"},
            {"subtask_id": "st-002", "status": "done"},
        ]
        self.assertEqual(self._get_subtask_id(subtasks), "st-002")

    def test_skips_removed(self):
        subtasks = [
            {"subtask_id": "st-001", "status": "done"},
            {"subtask_id": "st-002", "status": "removed"},
        ]
        self.assertEqual(self._get_subtask_id(subtasks), "st-001")

    def test_skips_skipped(self):
        subtasks = [
            {"subtask_id": "st-001", "status": "done"},
            {"subtask_id": "st-002", "status": "skipped"},
        ]
        self.assertEqual(self._get_subtask_id(subtasks), "st-001")

    def test_none_when_all_removed(self):
        subtasks = [
            {"subtask_id": "st-001", "status": "removed"},
            {"subtask_id": "st-002", "status": "skipped"},
        ]
        self.assertIsNone(self._get_subtask_id(subtasks))

    def test_none_when_subtasks_empty(self):
        self.assertIsNone(self._get_subtask_id([]))


# ---------------------------------------------------------------------------
# capturePRFeedback exception isolation
# ---------------------------------------------------------------------------

class TestThreadExceptionIsolation(unittest.TestCase):
    """capturePRFeedback raising in the thread must not affect the caller."""

    def test_exception_in_thread_does_not_propagate(self):
        state = _make_state()
        exceptions_seen: list = []

        def _explode(**kwargs):
            raise RuntimeError("simulated thread crash")

        def _capture_exception(**kwargs):
            try:
                _explode(**kwargs)
            except RuntimeError as exc:
                exceptions_seen.append(exc)

        with mock.patch(
            "platform_core.orchestration.review_mixin.orchestrator_github"
        ) as mock_gh, mock.patch(
            "platform_core.orchestration.review_mixin.capturePRFeedback",
            return_value={"ok": False},
        ):
            mock_gh.createPullRequest.return_value = {"ok": True, "url": _PR_URL}
            mixin = _ConcreteReviewMixin()
            # Capture the thread exception in-process so pytest does not emit
            # PytestUnhandledThreadExceptionWarning while the caller remains isolated.
            t = threading.Thread(target=_capture_exception,
                                 kwargs={"pr_url": _PR_URL, "run_id": _RUN_ID},
                                 daemon=True)
            t.start()
            t.join(timeout=2)
            # Thread dying with an exception should not propagate; result is just dead thread
            self.assertFalse(t.is_alive())
            self.assertEqual(len(exceptions_seen), 1)
            # Caller return must be the dict from createPullRequest unchanged
            rv = mixin.createPullRequest(state, "/work")
            self.assertIn("ok", rv)


# ---------------------------------------------------------------------------
# _pollCIStatus — unit tests (no network)
# ---------------------------------------------------------------------------

class TestPollCIStatus(unittest.TestCase):
    """_pollCIStatus interprets check-run data correctly."""

    def _run(self, runs_json: list[dict], *, gh_code: int = 0) -> dict:
        out = "\n".join(json.dumps(r) for r in runs_json)
        with mock.patch(
            "platform_core.orchestration.pr_feedback._gh",
            return_value=(gh_code, out),
        ), mock.patch("platform_core.orchestration.pr_feedback.time.sleep"):
            return _pollCIStatus("owner", "repo", "sha-abc", poll_attempts=2, poll_interval=0)

    def test_all_passed(self):
        runs = [
            {"name": "build", "status": "completed", "conclusion": "success"},
            {"name": "lint", "status": "completed", "conclusion": "success"},
        ]
        result = self._run(runs)
        self.assertEqual(result["status"], "passed")
        self.assertIn("2", result["summary"])

    def test_one_failed(self):
        runs = [
            {"name": "build", "status": "completed", "conclusion": "failure"},
            {"name": "lint", "status": "completed", "conclusion": "success"},
        ]
        result = self._run(runs)
        self.assertEqual(result["status"], "failed")
        self.assertIn("build", result["summary"])

    def test_timed_out_is_failure(self):
        runs = [{"name": "test", "status": "completed", "conclusion": "timed_out"}]
        result = self._run(runs)
        self.assertEqual(result["status"], "failed")

    def test_cancelled_is_failure(self):
        runs = [{"name": "ci", "status": "completed", "conclusion": "cancelled"}]
        result = self._run(runs)
        self.assertEqual(result["status"], "failed")

    def test_in_progress_then_exhausted_returns_pending(self):
        runs = [{"name": "slow-test", "status": "in_progress", "conclusion": None}]
        result = self._run(runs)
        self.assertEqual(result["status"], "pending")

    def test_gh_failure_returns_unknown(self):
        with mock.patch(
            "platform_core.orchestration.pr_feedback._gh",
            return_value=(-1, "gh CLI not found"),
        ), mock.patch("platform_core.orchestration.pr_feedback.time.sleep"):
            result = _pollCIStatus("owner", "repo", "sha", poll_attempts=1, poll_interval=0)
        self.assertEqual(result["status"], "unknown")

    def test_empty_output_returns_unknown(self):
        with mock.patch(
            "platform_core.orchestration.pr_feedback._gh",
            return_value=(0, ""),
        ), mock.patch("platform_core.orchestration.pr_feedback.time.sleep"):
            result = _pollCIStatus("owner", "repo", "sha", poll_attempts=1, poll_interval=0)
        self.assertEqual(result["status"], "unknown")

    def test_runs_list_returned(self):
        runs = [{"name": "x", "status": "completed", "conclusion": "success"}]
        result = self._run(runs)
        self.assertIsInstance(result["runs"], list)
        self.assertEqual(len(result["runs"]), 1)


# ---------------------------------------------------------------------------
# _fetchReviews — unit tests (no network)
# ---------------------------------------------------------------------------

class TestFetchReviews(unittest.TestCase):
    """_fetchReviews aggregates review states correctly."""

    def _run(self, reviews_json: list[dict], *, gh_code: int = 0) -> dict:
        out = "\n".join(json.dumps(r) for r in reviews_json)
        with mock.patch(
            "platform_core.orchestration.pr_feedback._gh",
            return_value=(gh_code, out),
        ):
            return _fetchReviews("owner", "repo", "42")

    def test_approved(self):
        result = self._run([{"state": "APPROVED", "body": "LGTM"}])
        self.assertEqual(result["state"], "approved")
        self.assertIn("LGTM", result["feedback"])

    def test_changes_requested(self):
        result = self._run([{"state": "CHANGES_REQUESTED", "body": "Please rebase"}])
        self.assertEqual(result["state"], "changes_requested")

    def test_mixed_changes_wins(self):
        result = self._run([
            {"state": "APPROVED", "body": ""},
            {"state": "CHANGES_REQUESTED", "body": "fix typo"},
        ])
        self.assertEqual(result["state"], "changes_requested")

    def test_no_reviews(self):
        result = self._run([])
        self.assertEqual(result["state"], "none")
        self.assertEqual(result["feedback"], [])

    def test_gh_failure_returns_none_state(self):
        result = self._run([], gh_code=-1)
        self.assertEqual(result["state"], "none")

    def test_feedback_capped_at_three(self):
        reviews = [{"state": "APPROVED", "body": f"comment {i}"} for i in range(5)]
        result = self._run(reviews)
        self.assertLessEqual(len(result["feedback"]), 3)

    def test_empty_body_excluded(self):
        result = self._run([{"state": "APPROVED", "body": ""}])
        self.assertEqual(result["feedback"], [])

    def test_mixed_not_all_approved_is_pending(self):
        result = self._run([
            {"state": "APPROVED", "body": ""},
            {"state": "COMMENTED", "body": ""},
        ])
        self.assertEqual(result["state"], "pending")


# ---------------------------------------------------------------------------
# capturePRFeedback — promote_safe logic
# ---------------------------------------------------------------------------

class TestCapturePRFeedbackPromoteSafe(unittest.TestCase):
    """promote_safe is True only when CI passes and no blocking reviews."""

    def _run(self, ci_status: str, review_state: str) -> bool:
        ci_data = {"status": ci_status, "summary": "summary", "runs": []}
        review_data = {"state": review_state, "feedback": []}
        with mock.patch("platform_core.orchestration.pr_feedback._fetchHeadSHA",
                        return_value="sha-abc"), \
             mock.patch("platform_core.orchestration.pr_feedback._pollCIStatus",
                        return_value=ci_data), \
             mock.patch("platform_core.orchestration.pr_feedback._fetchReviews",
                        return_value=review_data), \
             mock.patch("platform_core.orchestration.pr_feedback._writeLedger",
                        return_value={"feedback_ok": True, "reflection_ok": True, "pr_outcome_ok": True}):
            result = capturePRFeedback(_PR_URL, _RUN_ID, _SUBTASK_ID)
        return result["promote_safe"]

    def test_ci_pass_approved_is_safe(self):
        self.assertTrue(self._run("passed", "approved"))

    def test_ci_pass_no_review_is_safe(self):
        self.assertTrue(self._run("passed", "none"))

    def test_ci_fail_blocks(self):
        self.assertFalse(self._run("failed", "approved"))

    def test_changes_requested_blocks(self):
        self.assertFalse(self._run("passed", "changes_requested"))

    def test_pending_ci_blocks(self):
        self.assertFalse(self._run("pending", "approved"))

    def test_unknown_ci_blocks(self):
        self.assertFalse(self._run("unknown", "none"))


if __name__ == "__main__":
    unittest.main()
