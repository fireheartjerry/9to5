"""Unit tests for SIE Layer 1 retrieval (embeddings mocked -- no Ollama needed)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from memory import experience, retrieval


class TestVectorMath(unittest.TestCase):
    def test_pack_unpack_roundtrip(self):
        vec = [0.1, -0.5, 1.0, 3.25]
        out = retrieval.unpack(retrieval.pack(vec))
        for a, b in zip(vec, out):
            self.assertAlmostEqual(a, b, places=5)

    def test_cosine_bounds_and_degenerate(self):
        self.assertAlmostEqual(retrieval.cosine([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(retrieval.cosine([1, 0], [0, 1]), 0.0)
        self.assertAlmostEqual(retrieval.cosine([1, 1], [-1, -1]), -1.0)
        self.assertEqual(retrieval.cosine([0, 0], [1, 1]), 0.0)   # zero vector -> 0
        self.assertEqual(retrieval.cosine([1], [1, 2]), 0.0)      # length mismatch -> 0


class TestRetrieval(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()
        retrieval.reset_embed_cache()
        # Drop any pooled connection a prior test left open to a now-deleted temp db --
        # without this, the per-thread pool can hand back a stale connection (to the old
        # inode), so seeds land in one db while retrieve() reads another -> empty hits and
        # a flaky IndexError. Reset makes each test open a fresh connection to its own db.
        experience._reset_schema_cache()

    def tearDown(self):
        mock.patch.stopall()
        experience._reset_schema_cache()   # release this test's pooled conn before unlinking
        for p in self.dir.rglob("*"):
            if p.is_file():
                p.unlink()
        self.dir.rmdir()

    def _seed(self, st_id, vec, passed=True, **extra):
        experience.record_subtask("r1", {
            "subtask_id": st_id, "title": f"title-{st_id}", "status": "done",
            "verify_result": {"passed": passed}, "session": {"attempts": 1, **extra},
        }, db_path=self.db)
        experience.set_subtask_embedding("r1", st_id, retrieval.pack(vec), db_path=self.db)

    def test_write_path_and_backfill_share_embedText_seam(self):
        # B26: the live write path and the nightly backfill must compose their vector through the
        # SAME _embedText(goal, title) helper, or backfilled rows land in a different vector space.
        with mock.patch.object(retrieval, "_embedText", return_value=[1.0, 0.0]) as m:
            retrieval.embed_and_store("r1", "st-live", "the goal", "the title", db_path=self.db)
        m.assert_called_once_with("the goal", "the title")

        # Seed a passing, un-embedded row; backfill must route through _embedText too.
        experience.record_subtask("r1", {
            "subtask_id": "st-bf", "title": "backfill title", "status": "done",
            "verify_result": {"passed": True}, "session": {"attempts": 1},
        }, db_path=self.db)
        with mock.patch.object(retrieval, "_embedText", return_value=[1.0, 0.0]) as m2:
            retrieval.backfill_embeddings(db_path=self.db)
        m2.assert_any_call("", "backfill title")

    def test_top_k_ranks_by_similarity(self):
        self._seed("st-001", [1.0, 0.0, 0.0])
        self._seed("st-002", [0.0, 1.0, 0.0])
        self._seed("st-003", [0.9, 0.1, 0.0])
        hits = retrieval.top_k_similar([1.0, 0.0, 0.0], k=2, db_path=self.db)
        self.assertEqual([h["st_id"] for h in hits], ["st-001", "st-003"])  # closest two
        self.assertGreater(hits[0]["score"], hits[1]["score"])

    def test_top_k_excludes_failed_by_default(self):
        self._seed("st-001", [1.0, 0.0], passed=False)
        self._seed("st-002", [1.0, 0.0], passed=True)
        hits = retrieval.top_k_similar([1.0, 0.0], k=5, db_path=self.db)
        self.assertEqual([h["st_id"] for h in hits], ["st-002"])

    def test_retrieve_uses_embed_seam(self):
        self._seed("st-001", [1.0, 0.0, 0.0], effort="high")
        with mock.patch.object(retrieval, "_embed_call", return_value=[1.0, 0.0, 0.0]):
            hits = retrieval.retrieve("some goal", "do a thing", db_path=self.db)
        self.assertEqual(hits[0]["st_id"], "st-001")

    def test_retrieve_returns_empty_when_embedder_unavailable(self):
        self._seed("st-001", [1.0, 0.0], db_path=self.db) if False else self._seed("st-001", [1.0, 0.0])
        with mock.patch.object(retrieval, "_embed_call", return_value=None):
            self.assertEqual(retrieval.retrieve("g", "t", db_path=self.db), [])


class TestRendering(unittest.TestCase):
    def test_render_respects_token_budget(self):
        neighbors = [{"title": "t" * 400, "effort": "high", "attempt_count": 1}
                     for _ in range(20)]
        block = retrieval.render_lessons(neighbors, max_tokens=50)
        self.assertLessEqual(retrieval._approx_tokens(block), 60)  # cap honored (+header slack)

    def test_render_empty_is_empty_string(self):
        self.assertEqual(retrieval.render_lessons([]), "")

    def test_render_flags_multi_attempt(self):
        block = retrieval.render_lessons(
            [{"title": "tricky", "effort": "xhigh", "attempt_count": 3}], max_tokens=200)
        self.assertIn("tricky", block)
        self.assertIn("3 tries", block)

    def test_lessons_block_is_best_effort_empty(self):
        # No DB / no embedder -> empty string, never raises.
        with mock.patch.object(retrieval, "_embed_call", return_value=None):
            self.assertEqual(retrieval.lessons_block("g", "t"), "")
