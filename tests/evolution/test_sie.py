"""Unit tests for the Self-Improvement Orchestrator auto-runner (learning/sie.py).

Consolidated from test_sie.py, test_sie_evolution_steps.py, test_sie_insight_step.py,
test_sie_lock.py, and test_learning_sie.py: all five exercise learning/sie.py --
the weekly/maintenance step registry, the maintenance lock, and the PR-consolidation
step (_pr_consolidate).
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import config
from learning import sie
from memory import experience, retrieval
from memory.experience_schema import _reset_schema_cache


class TestSieMaintenance(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "CONTROL_DIR", self.dir / "control").start()
        mock.patch.object(config, "VAULT_DISK_ROOT", self.dir / "vault").start()
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()
        mock.patch.object(config, "SIE_KILL_SWITCH", False).start()
        # Keep maintenance fully offline + fast: no embedder, and an empty eval suite so
        # the verify runner doesn't spawn real subprocesses during the unit test.
        mock.patch.object(retrieval, "_embed_call", return_value=None).start()
        mock.patch.object(config, "EVAL_SUITE_DIR", self.dir / "nosuite").start()
        # Never let the auto-runner spawn real self-play runs or shell out during unit tests.
        mock.patch.object(config, "SELFPLAY_ENABLED", False).start()
        mock.patch.object(config, "SIE_BOOTSTRAP", False).start()
        retrieval.reset_embed_cache()

    def tearDown(self):
        mock.patch.stopall()
        # Release the pooled SQLite connection(s) maintenance opened before unlinking the temp
        # db, or Windows raises PermissionError (WinError 32: file in use) on the open inode/WAL.
        experience._reset_schema_cache()
        for p in sorted(self.dir.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
        self.dir.rmdir()

    def _seed(self):
        for i in range(3):
            experience.record_subtask(
                "r1",
                {
                    "subtask_id": f"st-{i}",
                    "title": "discord thing",
                    "status": "done",
                    "verify_result": {"passed": i > 0},
                    "session": {"effort": "high", "attempts": 1},
                },
                db_path=self.db,
            )

    def test_force_runs_all_steps_and_records_state(self):
        out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertEqual(
            set(out["steps"]),
            {
                "embeddings",
                "pr_consolidate",
                "consolidate",
                "insight",
                "policy_rebuild",
                "mine",
                "evaluate",
                "prompt_promotion",
                "lora_distillation",
                "dpo_distillation",
                "adapter_promotion",
                "meta_optimize",
                "self_play",
                "evolve",
                "evolve_promote",
                "curate",
                "curriculum_and_report",
            },
        )
        self.assertTrue(sie._state_path().exists())
        # This run deliberately uses an EMPTY eval suite (EVAL_SUITE_DIR -> nosuite) to stay offline
        # and fast; an empty suite is honestly reported as 'empty_suite', never falsely 'scored'.
        self.assertEqual(out["steps"]["evaluate"]["status"], "empty_suite")

    def test_throttled_second_call_skips(self):
        with mock.patch.object(config, "SIE_FORCE_WEEKLY", False):
            sie.run_maintenance(force=True, db_path=self.db)
            out = sie.run_maintenance(force=False, db_path=self.db)  # within window
        self.assertEqual(out["skipped"], "not_due")

    def test_kill_switch_skips(self):
        with mock.patch.object(config, "SIE_KILL_SWITCH", True):
            out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertEqual(out["skipped"], "kill_switch")

    def test_lock_prevents_overlap(self):
        lp = sie._lock_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text("999")  # another run holds the lock...
        # ...and it's ALIVE -- so the lock must NOT be reclaimed and maintenance skips. (A lock whose
        # owner PID is dead is correctly reclaimed; that path is covered by TestSieLock.)
        with mock.patch.object(sie, "_lock_owner_alive", return_value=True):
            out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertEqual(out["skipped"], "locked")

    def test_live_owner_older_than_1h_is_not_stolen(self):
        # B24: a still-LIVE owner must never be reclaimed, no matter how old the lock. The old
        # time-only rule stole any lock >1h, killing long-running (but live) maintenance passes.
        lp = sie._lock_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(str(os.getpid()), encoding="utf-8")  # our pid == provably alive
        old = time.time() - 2 * 3600  # 2h old
        os.utime(lp, (old, old))
        self.assertIsNone(sie._acquire_lock(), "stole a lock held by a live (but old) owner")

    def test_maintenance_rebuilds_policy_arms(self):
        self._seed()
        sie.run_maintenance(force=True, db_path=self.db)
        arms = experience.fetch_arms("discord", db_path=self.db)
        self.assertTrue(arms)  # policy rebuilt automatically, no human action

    def test_idempotent_second_force_run(self):
        self._seed()
        sie.run_maintenance(force=True, db_path=self.db)
        sie.run_maintenance(force=True, db_path=self.db)  # must not error or double-count
        arms = {a["action_json"]: a for a in experience.fetch_arms("discord", db_path=self.db)}
        self.assertEqual(arms['{"effort": "high"}']["pulls"], 3)

    def test_evolve_op_registered(self):
        out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertIn("evolve", out["steps"])

    def test_evolve_promote_op_registered(self):
        out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertIn("evolve_promote", out["steps"])

    def test_curate_op_registered(self):
        out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertIn("curate", out["steps"])

    def test_insight_op_registered(self):
        out = sie.run_maintenance(force=True, db_path=self.db)
        self.assertIn("insight", out["steps"])


def test_weekly_steps_include_evolution_steps():
    names = [name for name, _ in sie._weekly_steps(None)]
    for n in ("evolve", "evolve_promote", "curate"):
        assert n in names


class TestCurriculumAutoQueueGuardrails(unittest.TestCase):
    """B-security: curriculum auto-queue bypasses the human approval gate, so it must be
    opt-in (default OFF) and, once opted in, bounded like selfplay (busy-check, daily cap,
    cross-pass dedup). See learning/sie_curriculum.py."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        mock.patch.object(config, "CONTROL_DIR", self.dir / "control").start()

    def tearDown(self):
        mock.patch.stopall()
        for p in sorted(self.dir.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
        self.dir.rmdir()

    def _goals(self, n=3):
        return [{"family": f"fam{i}", "goal": f"practice fam{i}", "reason": "weak"} for i in range(n)]

    def test_disabled_by_default(self):
        # FULL_STACK defaults this on; under conservative master-off mode it must ship dark
        # (it bypasses the human approval gate, so opt-in only).
        from platform_core.app_config.llm import SieCfg
        fld = SieCfg.__dataclass_fields__["CURRICULUM_AUTO_QUEUE_ENABLED"]
        with mock.patch.dict(os.environ, {"FULL_STACK": "0"}, clear=False):
            os.environ.pop("CURRICULUM_AUTO_QUEUE_ENABLED", None)
            self.assertFalse(fld.default_factory(),
                             "must ship dark under FULL_STACK=0 (bypasses the human gate)")

    def test_noop_when_flag_unset(self):
        # Even with a strong trigger (>=5 new feedback + goals available), the auto-queue must
        # be a complete no-op while the flag is unset/False -- no spawn() call at all.
        with (
            mock.patch.object(config, "CURRICULUM_AUTO_QUEUE_ENABLED", False),
            mock.patch("learning.curriculum.generate_goals", return_value=self._goals()),
            mock.patch("learning.curriculum.write_suggestions"),
            mock.patch("learning.release.write_report"),
            mock.patch("notifications.work_launcher.spawn") as spawn_mock,
        ):
            out = sie._curriculum_and_report(None)
        spawn_mock.assert_not_called()
        self.assertEqual(out["auto_queued"], 0)
        self.assertEqual(out.get("auto_queue_skipped"), "disabled")

    def test_busy_check_blocks_auto_queue(self):
        with (
            mock.patch.object(config, "CURRICULUM_AUTO_QUEUE_ENABLED", True),
            mock.patch.object(sie, "_read_state", return_value={"last_full_at": "2020-01-01T00:00:00+00:00"}),
            mock.patch.object(sie, "_count_new_feedback_since_last_consolidation", return_value=10),
            mock.patch("learning.curriculum.generate_goals", return_value=self._goals()),
            mock.patch("learning.curriculum.write_suggestions"),
            mock.patch("learning.release.write_report"),
            mock.patch("notifications.work_launcher.activeRun", return_value=object()),
            mock.patch("notifications.work_launcher.spawn") as spawn_mock,
        ):
            out = sie._curriculum_and_report(None)
        spawn_mock.assert_not_called()
        self.assertEqual(out.get("auto_queue_skipped"), "busy")

    def test_daily_cap_enforced(self):
        with (
            mock.patch.object(config, "CURRICULUM_AUTO_QUEUE_ENABLED", True),
            mock.patch.object(config, "CURRICULUM_AUTO_QUEUE_MAX_PER_DAY", 2),
            mock.patch.object(sie, "_read_state", return_value={"last_full_at": "2020-01-01T00:00:00+00:00"}),
            mock.patch.object(sie, "_count_new_feedback_since_last_consolidation", return_value=10),
            mock.patch("learning.curriculum.generate_goals", return_value=self._goals(3)),
            mock.patch("learning.curriculum.write_suggestions"),
            mock.patch("learning.release.write_report"),
            mock.patch("notifications.work_launcher.activeRun", return_value=None),
            mock.patch("notifications.work_launcher.spawn") as spawn_mock,
        ):
            out = sie._curriculum_and_report(None)
        self.assertEqual(spawn_mock.call_count, 2)
        self.assertEqual(out["auto_queued"], 2)

    def test_dedup_skips_previously_queued_goal(self):
        goals = self._goals(1)
        key = f"{goals[0]['family']}:{goals[0]['goal']}"
        with (
            mock.patch.object(config, "CURRICULUM_AUTO_QUEUE_ENABLED", True),
            mock.patch.object(
                sie,
                "_read_state",
                return_value={
                    "last_full_at": "2020-01-01T00:00:00+00:00",
                    "curriculum_auto_queued_keys": [key],
                },
            ),
            mock.patch.object(sie, "_count_new_feedback_since_last_consolidation", return_value=10),
            mock.patch("learning.curriculum.generate_goals", return_value=goals),
            mock.patch("learning.curriculum.write_suggestions"),
            mock.patch("learning.release.write_report"),
            mock.patch("notifications.work_launcher.activeRun", return_value=None),
            mock.patch("notifications.work_launcher.spawn") as spawn_mock,
        ):
            out = sie._curriculum_and_report(None)
        spawn_mock.assert_not_called()
        self.assertEqual(out["auto_queued"], 0)
        self.assertEqual(out.get("auto_queue_skipped"), "daily_cap_or_dedup")

    def test_below_feedback_threshold_skips(self):
        with (
            mock.patch.object(config, "CURRICULUM_AUTO_QUEUE_ENABLED", True),
            mock.patch.object(sie, "_read_state", return_value={"last_full_at": "2020-01-01T00:00:00+00:00"}),
            mock.patch.object(sie, "_count_new_feedback_since_last_consolidation", return_value=4),
            mock.patch("learning.curriculum.generate_goals", return_value=self._goals()),
            mock.patch("learning.curriculum.write_suggestions"),
            mock.patch("learning.release.write_report"),
            mock.patch("notifications.work_launcher.spawn") as spawn_mock,
        ):
            out = sie._curriculum_and_report(None)
        spawn_mock.assert_not_called()
        self.assertEqual(out["auto_queued"], 0)


def test_maintenance_steps_includes_insight():
    names = [name for name, _ in sie._maintenance_steps(None)]
    assert "insight" in names


class TestSieLock(unittest.TestCase):
    """SIE maintenance lock must reclaim an ORPHANED lock (owner PID dead) immediately, not wait
    for the 1h staleness window -- maintenance runs on a daemon thread, so a process exiting
    mid-pass would otherwise block all future maintenance for an hour."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._p = mock.patch.object(config, "CONTROL_DIR", self.dir)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_orphaned_lock_with_dead_owner_is_reclaimed(self):
        lp = sie._lock_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text("999999999", encoding="utf-8")  # implausible -> definitely-dead PID
        got = sie._acquire_lock()
        self.assertIsNotNone(got, "did not reclaim a lock owned by a dead PID")
        self.assertEqual(lp.read_text(encoding="utf-8").strip(), str(os.getpid()))

    def test_lock_held_by_live_owner_is_not_stolen(self):
        lp = sie._lock_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(str(os.getpid()), encoding="utf-8")  # our own pid == alive
        self.assertIsNone(sie._acquire_lock(), "stole a lock held by a live process")


# ---------------------------------------------------------------------------
# Tests for the PR-consolidation step in learning/sie.py.
#
# Covers _pr_consolidate: failure-mode + lesson emission, gating logic, and
# provenance passthrough. Uses a temp DB so nothing touches prod state.
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
            "run1",
            "https://github.com/org/repo/pull/1",
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
            "run1",
            "https://github.com/org/repo/pull/2",
            {
                "ci_status": "failure",
                "ci_summary": "2 checks failed",
                "review_state": "",
                "promote_safe": False,
                "provenance": {"subtask_id": "st-001"},
            },
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
            "run1",
            "https://github.com/org/repo/pull/3",
            {
                "ci_status": "success",
                "review_state": "changes_requested",
                "promote_safe": False,
                "provenance": {"subtask_id": "st-002"},
            },
            db_path=self.db,
        )
        result = sie._pr_consolidate(db_path=self.db)
        self.assertEqual(result["gated"], 1)
        modes = experience.fetch_failure_modes(db_path=self.db)
        classes = {m["taxonomy_class"] for m in modes}
        self.assertIn("review_rejected", classes)

    def test_review_dismissed_emits_review_rejected_mode(self):
        experience.record_pr_outcome(
            "run1",
            "https://github.com/org/repo/pull/4",
            {"ci_status": "success", "review_state": "dismissed", "promote_safe": False},
            db_path=self.db,
        )
        sie._pr_consolidate(db_path=self.db)
        modes = experience.fetch_failure_modes(db_path=self.db)
        classes = {m["taxonomy_class"] for m in modes}
        self.assertIn("review_rejected", classes)

    def test_mixed_outcomes_counts_correctly(self):
        # 1 safe, 1 ci_failure, 1 review_rejected -> 2 gated, 2 modes, 2 lessons
        experience.record_pr_outcome(
            "run1",
            "https://github.com/org/repo/pull/10",
            {"ci_status": "success", "review_state": "approved", "promote_safe": True},
            db_path=self.db,
        )
        experience.record_pr_outcome(
            "run2",
            "https://github.com/org/repo/pull/11",
            {
                "ci_status": "failure",
                "review_state": "",
                "promote_safe": False,
                "provenance": {"subtask_id": "st-a"},
            },
            db_path=self.db,
        )
        experience.record_pr_outcome(
            "run3",
            "https://github.com/org/repo/pull/12",
            {
                "ci_status": "success",
                "review_state": "changes_requested",
                "promote_safe": False,
                "provenance": {"subtask_id": "st-b"},
            },
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
            "run1",
            "https://github.com/org/repo/pull/20",
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
            "run1",
            "https://github.com/org/repo/pull/30",
            {"ci_status": "failure", "promote_safe": False, "provenance": {"subtask_id": "st-lesson"}},
            db_path=self.db,
        )
        sie._pr_consolidate(db_path=self.db)
        lessons = experience.fetch_lessons(scope="pr_feedback", db_path=self.db)
        self.assertTrue(lessons, "expected at least one lesson in pr_feedback scope")

    def test_lesson_win_rate_is_zero_for_failed_pr(self):
        experience.record_pr_outcome(
            "run1",
            "https://github.com/org/repo/pull/31",
            {"ci_status": "failure", "promote_safe": False, "provenance": {"subtask_id": "st-lose"}},
            db_path=self.db,
        )
        sie._pr_consolidate(db_path=self.db)
        lessons = experience.fetch_lessons(scope="pr_feedback", db_path=self.db)
        self.assertTrue(all(lesson["win_rate"] == 0.0 for lesson in lessons))

    def test_lesson_text_contains_pr_url(self):
        url = "https://github.com/org/repo/pull/32"
        experience.record_pr_outcome(
            "run1",
            url,
            {"ci_status": "failure", "promote_safe": False, "provenance": {"subtask_id": "st-url"}},
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
            "run1",
            "https://github.com/org/repo/pull/40",
            {"ci_status": "failure", "promote_safe": False, "provenance": {"subtask_id": "st-scope"}},
            db_path=self.db,
        )
        sie._pr_consolidate(db_path=self.db)
        modes = experience.fetch_failure_modes("st-scope", db_path=self.db)
        self.assertTrue(modes, "expected failure mode scoped to st-scope")

    def test_idempotent_on_second_consolidate_call(self):
        experience.record_pr_outcome(
            "run1",
            "https://github.com/org/repo/pull/50",
            {"ci_status": "failure", "promote_safe": False, "provenance": {"subtask_id": "st-idem"}},
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
