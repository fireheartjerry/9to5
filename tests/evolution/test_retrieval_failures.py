"""Unit tests for SIE Layer-1 FAILURE-AWARE retrieval (embeddings mocked -- no Ollama).

Verifies that, behind ``RETRIEVAL_FAILURES_ENABLED``, the query-time injection path also
surfaces similar past FAILED subtasks as distinctly-tagged warnings alongside successes,
reusing the SAME embedding scan and honoring the token budget -- and that with the flag OFF
the injected block is byte-identical to today's success-only behavior.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from memory import experience, retrieval

QVEC = [1.0, 0.0, 0.0]


class TestFailureAwareRetrieval(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()
        retrieval.reset_embed_cache()
        experience._reset_schema_cache()

    def tearDown(self):
        mock.patch.stopall()
        experience._reset_schema_cache()
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

    # ---- top_k_failures pulls ONLY explicitly-failed rows from the same scan ----

    def test_top_k_failures_returns_only_failed(self):
        self._seed("st-ok", QVEC, passed=True)
        self._seed("st-bad", QVEC, passed=False)
        hits = retrieval.top_k_failures(QVEC, k=5, db_path=self.db)
        self.assertEqual([h["st_id"] for h in hits], ["st-bad"])

    # ---- flag=True: a distinct failure warning is injected alongside successes ----

    def test_flag_true_injects_failure_warning(self):
        self._seed("st-ok", QVEC, passed=True)
        self._seed("st-bad", QVEC, passed=False)
        with mock.patch.object(config, "RETRIEVAL_FAILURES_ENABLED", True), \
                mock.patch.object(config, "RETRIEVAL_FAILURES_K", 2), \
                mock.patch.object(retrieval, "_embed_call", return_value=QVEC):
            block = retrieval.lessons_block("some goal", "do a thing", db_path=self.db)
        self.assertIn("FAILURE", block)
        self.assertIn("title-st-bad", block)              # the failed neighbor surfaced
        # It must be tagged as a failure, distinct from the successes block.
        self.assertIn("FAILED", block.upper())

    # ---- flag=False: byte-identical to the success-only baseline ----

    def test_flag_false_identical_to_baseline(self):
        self._seed("st-ok", QVEC, passed=True)
        self._seed("st-bad", QVEC, passed=False)
        with mock.patch.object(config, "RETRIEVAL_FAILURES_ENABLED", False), \
                mock.patch.object(retrieval, "_embed_call", return_value=QVEC):
            with_flag_off = retrieval.lessons_block("some goal", "do a thing", db_path=self.db)

        # Baseline = success-only rendering the module produced before this feature: recompute
        # it directly from the same neighbors so the comparison can't drift.
        with mock.patch.object(retrieval, "_embed_call", return_value=QVEC):
            neighbors = retrieval.retrieve_content("some goal", "do a thing", db_path=self.db)
        baseline_block = retrieval.render_solutions(neighbors) or retrieval.render_lessons(neighbors)
        baseline = (baseline_block + "\n") if baseline_block else ""

        self.assertEqual(with_flag_off, baseline)
        self.assertNotIn("title-st-bad", with_flag_off)   # no failure leaks with flag off

    # ---- the failure block honors the token budget ----

    def test_render_failures_respects_token_budget(self):
        neighbors = [{"title": "f" * 400, "effort": "high"} for _ in range(20)]
        block = retrieval.render_failures(neighbors, max_tokens=50)
        self.assertLessEqual(retrieval._approx_tokens(block), 60)  # cap honored (+header slack)

    def test_render_failures_empty_is_empty_string(self):
        self.assertEqual(retrieval.render_failures([]), "")

