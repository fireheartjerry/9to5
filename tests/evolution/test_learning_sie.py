"""Tests for the PR-consolidation step in learning/sie.py.

Covers _pr_consolidate: failure-mode + lesson emission, gating logic, and
provenance passthrough. Uses a temp DB so nothing touches prod state.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import config
from learning import sie
from memory import experience
from memory.experience_schema import _reset_schema_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_dir: Path) -> Path:
    p = tmp_dir / "test.db"
    experience.init(p)
    return p


class PrConsolidateBase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        self.db = _make_db(self._tmp)
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()

    def tearDown(self):
        mock.patch.stopall()
        _reset_schema_cache()
        for p in sorted(self._tmp.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
        self._tmp.rmdir()


# ---------------------------------------------------------------------------
# _pr_consolidate — happy path
# ---------------------------------------------------------------------------

class TestPrConsolidateHappyPath(PrConsolidateBase):

    def test_empty_outcomes_returns_all_zeros(self):
        result = sie._pr_consolidate(db_path=self.db)
        self.assertEqual(result["outcomes"], 0)
        self.assertEqual(result["gated"], 0)
        self.assertEqual(result["failure_modes_written"], 0)
        self.assertEqual(result["lessons_emitted"], 0)

    def test_safe_pr_not_gated(self):
        experience.record_pr_outcome(
            "run1", "https://github.com/org/repo/pull/1",
            {"ci_status": "success", "review_state": "approved", "promote_safe": True},
            db_path=self.db,
        )
        result = sie._pr_consolidate(db_path=self.db)
        self.assertEqual(result["outcomes"], 1)
        self.assertEqual(result["gated"], 0)
        self.assertEqual(result["failure_modes_written"], 0)
        self.assertEqual(result["lessons_emitted"], 0)

    def test_ci_failure_gated_and_emits_ci_failure_mode(self):
        experience.record_pr_outcome(
            "run1", "https://github.com/org/repo/pull/2",
            {"ci_status": "failure", "ci_summary": "2 checks failed",
             "review_state": "", "promote_safe": False,
             "provenance": {"subtask_id": "st-001"}},
            db_path=self.db,
        )
        result = sie._pr_consolidate(db_path=self.db)
        self.assertEqual(result["gated"], 1)
        self.assertEqual(result["failure_modes_written"], 1)
        modes = experience.fetch_failure_modes(db_path=self.db)
        classes = {m["taxonomy_class"] for m in modes}
        self.assertIn("ci_failure", classes)

    def test_review_changes_requested_emits_review_rejected_mode(self):
        experience.record_pr_outcome(
            "run1", "https://github.com/org/repo/pull/3",
            {"ci_status": "success", "review_state": "changes_requested",
             "promote_safe": False, "provenance": {"subtask_id": "st-002"}},
            db_path=self.db,
        )
        result = sie._pr_consolidate(db_path=self.db)
        self.assertEqual(result["gated"], 1)
        modes = experience.fetch_failure_modes(db_path=self.db)
        classes = {m["taxonomy_class"] for m in modes}
        self.assertIn("review_rejected", classes)

    def test_review_dismissed_emits_review_rejected_mode(self):
        experience.record_pr_outcome(
            "run1", "https://github.com/org/repo/pull/4",
            {"ci_status": "success", "review_state": "dismissed",
             "promote_safe": False},
            db_path=self.db,
        )
        sie._pr_consolidate(db_path=self.db)
        modes = experience.fetch_failure_modes(db_path=self.db)
        classes = {m["taxonomy_class"] for m in modes}
        self.assertIn("review_rejected", classes)

    def test_mixed_outcomes_counts_correctly(self):
        # 1 safe, 1 ci_failure, 1 review_rejected -> 2 gated, 2 modes, 2 lessons
        experience.record_pr_outcome(
            "run1", "https://github.com/org/repo/pull/10",
            {"ci_status": "success", "review_state": "approved", "promote_safe": True},
            db_path=self.db,
        )
        experience.record_pr_outcome(
            "run2", "https://github.com/org/repo/pull/11",
            {"ci_status": "failure", "review_state": "", "promote_safe": False,
             "provenance": {"subtask_id": "st-a"}},
            db_path=self.db,
        )
        experience.record_pr_outcome(
            "run3", "https://github.com/org/repo/pull/12",
            {"ci_status": "success", "review_state": "changes_requested",
             "promote_safe": False, "provenance": {"subtask_id": "st-b"}},
            db_path=self.db,
        )
        result = sie._pr_consolidate(db_path=self.db)
        self.assertEqual(result["outcomes"], 3)
        self.assertEqual(result["gated"], 2)
        self.assertEqual(result["failure_modes_written"], 2)
        self.assertEqual(result["lessons_emitted"], 2)

    def test_null_promote_safe_is_gated(self):
        # NULL promote_safe (no explicit value) is treated as unsafe -> must be gated
        experience.record_pr_outcome(
            "run1", "https://github.com/org/repo/pull/20",
            {},  # no promote_safe key -> stored as NULL
            db_path=self.db,
        )
        result = sie._pr_consolidate(db_path=self.db)
        self.assertEqual(result["gated"], 1)


# ---------------------------------------------------------------------------
# _pr_consolidate — lesson content
# ---------------------------------------------------------------------------

class TestPrConsolidateLessonContent(PrConsolidateBase):

    def test_lesson_stored_in_pr_feedback_scope(self):
        experience.record_pr_outcome(
            "run1", "https://github.com/org/repo/pull/30",
            {"ci_status": "failure", "promote_safe": False,
             "provenance": {"subtask_id": "st-lesson"}},
            db_path=self.db,
        )
        sie._pr_consolidate(db_path=self.db)
        lessons = experience.fetch_lessons(scope="pr_feedback", db_path=self.db)
        self.assertTrue(lessons, "expected at least one lesson in pr_feedback scope")

    def test_lesson_win_rate_is_zero_for_failed_pr(self):
        experience.record_pr_outcome(
            "run1", "https://github.com/org/repo/pull/31",
            {"ci_status": "failure", "promote_safe": False,
             "provenance": {"subtask_id": "st-lose"}},
            db_path=self.db,
        )
        sie._pr_consolidate(db_path=self.db)
        lessons = experience.fetch_lessons(scope="pr_feedback", db_path=self.db)
        self.assertTrue(all(lesson["win_rate"] == 0.0 for lesson in lessons))

    def test_lesson_text_contains_pr_url(self):
        url = "https://github.com/org/repo/pull/32"
        experience.record_pr_outcome(
            "run1", url,
            {"ci_status": "failure", "promote_safe": False,
             "provenance": {"subtask_id": "st-url"}},
            db_path=self.db,
        )
        sie._pr_consolidate(db_path=self.db)
        lessons = experience.fetch_lessons(scope="pr_feedback", db_path=self.db)
        self.assertTrue(any(url in lesson["text"] for lesson in lessons))


# ---------------------------------------------------------------------------
# _pr_consolidate — provenance passthrough
# ---------------------------------------------------------------------------

class TestPrConsolidateProvenance(PrConsolidateBase):

    def test_failure_mode_scoped_to_subtask_id(self):
        experience.record_pr_outcome(
            "run1", "https://github.com/org/repo/pull/40",
            {"ci_status": "failure", "promote_safe": False,
             "provenance": {"subtask_id": "st-scope"}},
            db_path=self.db,
        )
        sie._pr_consolidate(db_path=self.db)
        modes = experience.fetch_failure_modes("st-scope", db_path=self.db)
        self.assertTrue(modes, "expected failure mode scoped to st-scope")

    def test_idempotent_on_second_consolidate_call(self):
        experience.record_pr_outcome(
            "run1", "https://github.com/org/repo/pull/50",
            {"ci_status": "failure", "promote_safe": False,
             "provenance": {"subtask_id": "st-idem"}},
            db_path=self.db,
        )
        r1 = sie._pr_consolidate(db_path=self.db)
        r2 = sie._pr_consolidate(db_path=self.db)
        # Both runs see the same outcome count; second run may upsert (0 new modes/lessons)
        self.assertEqual(r1["outcomes"], r2["outcomes"])
        modes = experience.fetch_failure_modes(db_path=self.db)
        # Upsert must not duplicate rows
        ci_modes = [m for m in modes if m["taxonomy_class"] == "ci_failure"]
        self.assertEqual(len(ci_modes), 1)
