"""Unit tests for SIE Layer 2 consolidation (learning/lessons.py)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import lessons
from memory import experience


class TestFamily(unittest.TestCase):
    def test_family_skips_stopwords(self):
        self.assertEqual(lessons.family_of("add discord embed"), "discord")
        self.assertEqual(lessons.family_of("Fix the webdash refresh"), "webdash")

    def test_family_prefers_signature_tags(self):
        self.assertEqual(lessons.family_of("anything", "Discord"), "discord")


class TestConsolidate(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()
        mock.patch.object(config, "LESSONS_MIN_SUPPORT", 3).start()
        mock.patch.object(config, "LESSONS_WIN_GAP", 0.2).start()

    def tearDown(self):
        mock.patch.stopall()
        # release pooled SQLite connection(s) before unlinking the temp db (Windows WinError 32)
        experience._reset_schema_cache()
        for p in self.dir.rglob("*"):
            if p.is_file():
                p.unlink()
        for p in sorted(self.dir.rglob("*"), reverse=True):
            if p.is_dir():
                p.rmdir()
        self.dir.rmdir()

    def _seed(self, fam, effort, passed, n):
        for i in range(n):
            experience.record_subtask("r1", {
                "subtask_id": f"{fam}-{effort}-{int(passed)}-{i}", "title": f"{fam} thing",
                "status": "done", "verify_result": {"passed": passed},
                "session": {"effort": effort, "attempts": 1},
            }, db_path=self.db)

    def test_emits_effort_lesson_on_clear_gap(self):
        self._seed("discord", "high", True, 3)
        self._seed("discord", "default", False, 3)
        out = lessons.consolidate(db_path=self.db, write_digest=False)
        self.assertEqual(out["lessons"], 1)
        rows = experience.fetch_lessons("effort", db_path=self.db)
        self.assertEqual(rows[0]["signature_tags"], "discord")
        self.assertIn("prefer high", rows[0]["text"])

    def test_no_lesson_below_min_support(self):
        self._seed("webdash", "high", True, 1)
        self._seed("webdash", "default", False, 1)
        out = lessons.consolidate(db_path=self.db, write_digest=False)
        self.assertEqual(out["lessons"], 0)

    def test_no_lesson_when_gap_too_small(self):
        # high 2/3 pass, default 1/2 pass -> gap ~0.17 < 0.2
        self._seed("api", "high", True, 2)
        self._seed("api", "high", False, 1)
        self._seed("api", "default", True, 1)
        self._seed("api", "default", False, 1)
        out = lessons.consolidate(db_path=self.db, write_digest=False)
        self.assertEqual(out["lessons"], 0)

    def test_idempotent_rebuild(self):
        self._seed("discord", "high", True, 3)
        self._seed("discord", "default", False, 3)
        lessons.consolidate(db_path=self.db, write_digest=False)
        lessons.consolidate(db_path=self.db, write_digest=False)
        self.assertEqual(len(experience.fetch_lessons(db_path=self.db)), 1)

    def test_rebuild_failure_leaves_prior_lessons_intact(self):
        # B25: clear+rebuild runs in ONE transaction, so a failure mid-rebuild rolls back the
        # DELETE and the prior lessons survive -- never a half-cleared table.
        lessons._rebuild_lessons([("effort", "discord", "old lesson", 3, 0.9)], db_path=self.db)
        self.assertEqual(len(experience.fetch_lessons(db_path=self.db)), 1)
        # Second rebuild fails on the SECOND row (win_rate not floatable) AFTER the DELETE +
        # first INSERT have run -- all must roll back.
        with self.assertRaises(Exception):
            lessons._rebuild_lessons(
                [("effort", "discord", "new good", 3, 0.8),
                 ("effort", "api", "new bad", 3, "NOT_A_FLOAT")], db_path=self.db)
        rows = experience.fetch_lessons(db_path=self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "old lesson")

    def test_digest_written(self):
        self._seed("discord", "high", True, 3)
        self._seed("discord", "default", False, 3)
        digest = self.dir / "lessons.md"
        lessons.consolidate(db_path=self.db, write_digest=True, digest_path=digest)
        self.assertTrue(digest.exists())
        self.assertIn("prefer high", digest.read_text(encoding="utf-8"))
