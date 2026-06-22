"""CI coverage for the virtual-operator end-to-end suite: a scripted 'human' drives a
full simulated run through the real control surfaces and we assert the outcome."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from testing import e2e
from testing.operator import VirtualOperator


class TestE2EOperator(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "tasks").mkdir()
        (self.dir / "control").mkdir()
        self._patches = [
            mock.patch.object(config, "STATE_DIR", self.dir / "tasks"),
            mock.patch.object(config, "CONTROL_DIR", self.dir / "control"),
            mock.patch("orchestrator.refreshClaudeKnowledge", lambda *a, **k: ""),
            mock.patch("orchestrator.startWebDashboard", lambda *a, **k: None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_happy_path_web_surface(self):
        r = e2e.runScenario("happy-web", "build a calculator app", e2e._happy, surface="web")
        self.assertTrue(r.ok, r)
        self.assertEqual(r.status, "done")
        self.assertIn(("approve", ""), r.actions)

    def test_happy_path_command_spine(self):
        r = e2e.runScenario("happy-bus", "build a calculator app", e2e._happy, surface="bus")
        self.assertTrue(r.ok, r)
        self.assertEqual(r.status, "done")

    def test_reject_plan_aborts(self):
        r = e2e.runScenario("reject", "build a thing", e2e._reject_plan,
                            expect_status="aborted", surface="web")
        self.assertTrue(r.ok, r)
        self.assertEqual(r.status, "aborted")

    def test_abort_at_gate(self):
        r = e2e.runScenario("abort", "build a thing", e2e._abort_at_gate,
                            expect_status="aborted", surface="bus")
        self.assertTrue(r.ok, r)

    def test_pause_resume_then_finish(self):
        r = e2e.runScenario("pause-resume", "build a calculator app",
                            e2e._pause_resume_then_finish, expect_status="done", surface="web")
        self.assertTrue(r.ok, r)

    def test_skip_at_gate_removes_subtask(self):
        r = e2e.runScenario("skip", "build (1) add (2) sub (3) mul", e2e._skip_at_gate,
                            surface="web", n_subtasks=3)
        self.assertTrue(r.ok, r)
        self.assertTrue(any(s["status"] == "removed" for s in r.summary["subtasks"]), r.summary)

    def test_add_at_gate_adds_subtask(self):
        r = e2e.runScenario("add", "build (1) add (2) sub (3) mul", e2e._add_at_gate,
                            surface="bus", n_subtasks=3)
        self.assertTrue(r.ok, r)
        self.assertGreaterEqual(len(r.summary["subtasks"]), 4)   # 3 planned + 1 the human added

    def test_adversary_holds_the_pr(self):
        r = e2e.runScenario("hold", "build a calculator app", e2e._happy, surface="web",
                            review=e2e._challengedReview, auto_pr=True)
        self.assertTrue(r.ok, r)
        self.assertTrue(r.summary["pr"]["skipped"])
        self.assertIn("HOLD", r.summary["pr"]["reason"])   # the challenged verdict actually held it

    def test_full_builtin_suite_passes(self):
        results = e2e.runSuite()
        failed = [r for r in results if not r.ok]
        self.assertEqual(failed, [], failed)

    def test_operator_rejects_bad_surface(self):
        with self.assertRaises(ValueError):
            VirtualOperator("tid", surface="telepathy")


if __name__ == "__main__":
    unittest.main()
