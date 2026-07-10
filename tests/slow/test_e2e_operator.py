"""CI coverage for the virtual-operator end-to-end suite: a scripted 'human' drives a
full simulated run through the real control surfaces and we assert the outcome."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from platform_core.simulator.testing import e2e
from platform_core.simulator.testing.operator import VirtualOperator


class TestE2EOperator(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "tasks").mkdir()
        (self.dir / "control").mkdir()
        self._patches = [
            mock.patch.object(config, "STATE_DIR", self.dir / "tasks"),
            mock.patch.object(config, "CONTROL_DIR", self.dir / "control"),
            # _runPreamble calls refreshClaudeKnowledge via the name bound INTO run_phase_mixin
            # (from ...knowledge_refresh import refreshClaudeKnowledge), so patch THAT name -- patching
            # orchestrator.refreshClaudeKnowledge was a no-op and let the real ~16s refresh run,
            # pushing the plan gate past the operator's waitForGate timeout (flaky abort/gate tests).
            mock.patch("platform_core.orchestration.run_phase_mixin.refreshClaudeKnowledge",
                       lambda *a, **k: ""),
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

    def test_sim_run_never_posts_to_live_discord(self):
        """Regression: a simulated run must NOT hit the real channel even with live creds.
        Milestone embeds gate on DISCORD_BOT_TOKEN+DISCORD_CHANNEL_ID, so runScenario's _FORCED must
        blank both. Inject FAKE LIVE creds, spy on sendEmbed (so NO real post happens regardless),
        and assert every milestone attempt during the run saw blanked creds. Deliberately decoupled
        from r.ok / sim completion -- the no-live-post invariant must hold even if the sim is slow."""
        import notifications.discord_bot as discord
        seen = []

        def _spy(*a, **k):
            seen.append((config.DISCORD_BOT_TOKEN, config.DISCORD_CHANNEL_ID))
            return None  # never touch the network

        with mock.patch.object(config, "DISCORD_BOT_TOKEN", "FAKE-LIVE-TOKEN"), \
                mock.patch.object(config, "DISCORD_CHANNEL_ID", 999999999), \
                mock.patch.object(discord, "sendEmbed", side_effect=_spy):
            # Short timeout: milestone embeds (architect_done / plan_ready) fire early, so we observe
            # the cred state without needing the full gated run to finish.
            e2e.runScenario("no-post", "build a calculator app", e2e._happy, surface="web", timeout=8)
        self.assertTrue(seen, "expected the sim to attempt at least one milestone embed")
        for tok, chan in seen:
            self.assertEqual((tok, chan), ("", 0),
                             "sim attempted a Discord post with LIVE creds -- _FORCED must blank them")

    def test_operator_rejects_bad_surface(self):
        with self.assertRaises(ValueError):
            VirtualOperator("tid", surface="telepathy")
