"""Tests for NW3 post-mortems, NW5 KG, NW6 solution cache, NW4 reflection, NW7 research."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import (adapter_ops, knowledge_graph, meta_opt, postmortem,
                      reflection, solution_cache, toolsmith)
from memory import experience


class _Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()
        mock.patch.object(config, "MAX_SUBTASK_ATTEMPTS", 3).start()

    def tearDown(self):
        mock.patch.stopall()
        # release pooled SQLite connection(s) before unlinking the temp db (Windows WinError 32)
        experience._reset_schema_cache()
        for p in self.dir.rglob("*"):
            if p.is_file():
                p.unlink()
        self.dir.rmdir()

    def _sub(self, st_id, *, passed, status="done", attempts=1, title="discord task", spec=None,
             skills=None, approved=False):
        st = {
            "subtask_id": st_id, "title": title, "status": status,
            "verify_result": {"passed": passed},
            "session": {"attempts": attempts, "effort": "high",
                        "invocation_spec": spec, "skills": skills},
        }
        if approved:
            st["_adversary_verdict"] = "approved"
            st["_adversary_stub"] = 0
        experience.record_subtask("r1", st, db_path=self.db)


class TestPostmortem(_Base):
    def test_classifies_and_accretes_taxonomy(self):
        self._sub("st-1", passed=False, status="failed", attempts=3)
        self._sub("st-2", passed=False, status="failed", attempts=3)
        out = postmortem.run_postmortems(db_path=self.db)
        self.assertEqual(out["classified"], 2)
        modes = experience.fetch_failure_modes("discord", db_path=self.db)
        self.assertEqual(modes[0]["taxonomy_class"], "repeat_fail")
        self.assertEqual(modes[0]["occurrences"], 2)

    def test_guidance_for_family(self):
        self._sub("st-1", passed=False, status="failed", attempts=3)
        postmortem.run_postmortems(db_path=self.db)
        g = postmortem.guidance_for("discord embed", db_path=self.db)
        self.assertIn("FAILURE MODES", g)

    def test_passing_not_classified(self):
        self.assertIsNone(postmortem.classify({"verify_passed": 1}))


class TestSolutionCache(_Base):
    def test_build_and_warm_start(self):
        self._sub("st-1", passed=True, attempts=1, title="Build the webdash",
                  spec={"effort": "high"}, approved=True)
        solution_cache.build_from_ledger(db_path=self.db)
        hit = solution_cache.warm_start("build the webdash", db_path=self.db)
        self.assertIsNotNone(hit)
        self.assertIn("high", hit)

    def test_miss_returns_none(self):
        self.assertIsNone(solution_cache.warm_start("never seen", db_path=self.db))


class TestKnowledgeGraph(_Base):
    def test_build_family_nodes_and_context(self):
        self._sub("st-1", passed=True, title="discord embed")
        self._sub("st-2", passed=False, title="discord slash")
        knowledge_graph.build_from_ledger(db_path=self.db)
        ctx = knowledge_graph.context_for("discord thing", db_path=self.db)
        self.assertIn("CODEBASE NOTE", ctx)
        self.assertIn("discord", ctx)


class TestReflection(_Base):
    def test_parse_fenced_json(self):
        out = "...did the work...\n```json\n{\"approach\": \"x\", \"reusable_recipe\": \"r\"}\n```"
        s = reflection.parse(out)
        self.assertEqual(s["approach"], "x")

    def test_trust_rejects_claim_on_failed_verify(self):
        s = {"approach": "x", "confidence": 0.9}
        self.assertFalse(reflection.trust(s, verify_passed=False, adversary_verdict=None))
        self.assertTrue(reflection.trust(s, verify_passed=True, adversary_verdict="approved"))

    def test_capture_only_trusts_consistent_reports(self):
        good = "```json\n{\"approach\":\"a\",\"reusable_recipe\":\"do X then Y\"}\n```"
        reflection.capture(run_id="r1", subtask_id="st-1", executor_output=good,
                           verify_passed=True, adversary_verdict="approved", db_path=self.db)
        reflection.capture(run_id="r1", subtask_id="st-2", executor_output=good,
                           verify_passed=False, db_path=self.db)
        self.assertEqual(reflection.recipes(db_path=self.db), ["do X then Y"])  # only the trusted one


class TestResearchTrack(_Base):
    def test_toolsmith_ranks_and_prunes(self):
        self._sub("st-1", passed=True, skills=["good"])
        self._sub("st-2", passed=True, skills=["good"])
        self._sub("st-3", passed=False, skills=["bad"])
        self._sub("st-4", passed=False, skills=["bad"])
        self._sub("st-5", passed=False, skills=["bad"])
        ranked = toolsmith.rank_tools(db_path=self.db)
        self.assertEqual(ranked[0]["skill"], "good")
        prune = toolsmith.prune_candidates(min_support=3, max_rate=0.3, db_path=self.db)
        self.assertEqual([p["skill"] for p in prune], ["bad"])

    def test_meta_opt_suggests_on_low_first_pass(self):
        for i in range(4):
            self._sub(f"st-{i}", passed=False, title="api task")
        sugg = meta_opt.suggest(db_path=self.db)
        self.assertTrue(any(s["knob"] == "MAX_SUBTASK_ATTEMPTS" for s in sugg))

    def test_adapter_soup_plan_and_overfit_signal(self):
        a = experience.register_adapter(base_model="b", tag="t-a", role="planner",
                                        lora_path="/a", db_path=self.db)
        b = experience.register_adapter(base_model="b", tag="t-b", role="replanner",
                                        lora_path="/b", db_path=self.db)
        experience.promote_adapter(a, db_path=self.db)
        experience.promote_adapter(b, db_path=self.db)
        self.assertEqual(len(adapter_ops.merge_plan(db_path=self.db)), 2)
        self.assertEqual(adapter_ops.soup(db_path=self.db)["skipped"], "no_merger")
        for v in (0.1, 0.3, 0.5, 0.7, 0.9):
            experience.record_eval({"fitness": v}, db_path=self.db)
        self.assertTrue(adapter_ops.overfit_signal(recent=5, db_path=self.db)["suspect"])


if __name__ == "__main__":
    unittest.main()
