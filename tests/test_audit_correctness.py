"""Correctness regressions from the gnarly audit:
- verify stdout_contains*/regex* families must require a clean exit (a crash that prints the needle
  was false-passing).
- an empty eval suite must record a transparent 'empty_suite' marker, not a fabricated 'scored'
  fitness (which polluted the SIE fitness series).
- retrieval must apply a similarity floor (#34) so irrelevant past lessons aren't force-fed.
- the 9to5 task-store hard boundary must be install-anchored (#39) so a target repo's own
  state/tasks/ isn't falsely blocked.
- the pre_pr approval gate hitting the deadline must finalize with the real status, not 'aborted' (#41).
- /ask NL-control must never abort a run without an explicit confirm (#42)."""
import threading
import types
import unittest
from unittest import mock

import config
import orchestrator
import orchestrator_control_mixin
from agents import hooks
from agents import hooks_selfmod
from agents.verifier import _evaluate
from learning import eval_harness
from memory import retrieval


class TestVerifyRequiresCleanExit(unittest.TestCase):
    def test_stdout_contains_fails_on_crash(self):
        self.assertFalse(_evaluate("stdout_contains:PASS", 1, "PASS\n"), "crash with needle false-passed")
        self.assertTrue(_evaluate("stdout_contains:PASS", 0, "PASS\n"))

    def test_stdout_regex_fails_on_crash(self):
        self.assertFalse(_evaluate("stdout_regex:OK", 1, "OK"))
        self.assertTrue(_evaluate("stdout_regex:OK", 0, "OK"))

    def test_compound_fails_on_crash(self):
        self.assertFalse(_evaluate("stdout_contains_all:A||B", 1, "A and B"))
        self.assertTrue(_evaluate("stdout_contains_all:A||B", 0, "A and B"))
        self.assertFalse(_evaluate("stdout_regex_all:A||B", 1, "A and B"))


class TestEmptyEvalSuite(unittest.TestCase):
    def test_empty_suite_records_marker_not_fitness(self):
        with mock.patch.object(eval_harness, "load_suite", return_value=[]), \
                mock.patch.object(eval_harness.experience, "record_eval") as rec:
            payload = eval_harness.run_suite(runner=lambda g: {"passed": True}, record=True)
        self.assertEqual(payload["status"], "empty_suite")
        self.assertNotIn("fitness", payload, "fabricated a fitness from an empty suite")
        self.assertEqual(payload["suite_size"], 0)
        rec.assert_called_once()


class TestRetrievalSimilarityFloor(unittest.TestCase):
    """#34: top_k_similar must drop neighbors below config.RETRIEVAL_MIN_SCORE so an unrelated
    past 'success' (cosine ~0) is never injected into an authoring prompt as a 'lesson'."""

    def _rows(self):
        # query [1,0]: 'hi' embeds [1,0] (cosine 1.0), 'lo' embeds [0,1] (cosine 0.0)
        return [
            {"st_id": "hi", "title": "hi", "embedding": retrieval.pack([1.0, 0.0])},
            {"st_id": "lo", "title": "lo", "embedding": retrieval.pack([0.0, 1.0])},
        ]

    def test_below_floor_dropped_above_kept(self):
        with mock.patch.object(retrieval.experience, "embedded_subtasks", return_value=self._rows()), \
                mock.patch.object(config, "RETRIEVAL_MIN_SCORE", 0.5):
            out = retrieval.top_k_similar([1.0, 0.0], k=5)
        self.assertEqual([r["st_id"] for r in out], ["hi"], "low-similarity neighbor was not filtered")

    def test_floor_zero_keeps_all(self):
        with mock.patch.object(retrieval.experience, "embedded_subtasks", return_value=self._rows()), \
                mock.patch.object(config, "RETRIEVAL_MIN_SCORE", 0.0):
            out = retrieval.top_k_similar([1.0, 0.0], k=5)
        self.assertEqual(len(out), 2, "a 0.0 floor must preserve legacy (no-floor) behavior")


class TestTaskStoreBoundaryAnchored(unittest.TestCase):
    """#39: the 9to5 task store must be anchored to the install root so a different repo's own
    state/tasks/ dir is NOT swept up by a bare 'state/tasks' substring boundary."""

    def setUp(self):
        # epoch present (skips the legacy-universe pull), non-self-ref (no core-file lock appended)
        self.state = types.SimpleNamespace(meta={
            "epoch": {"universe": {"hard_boundaries": []}},
            "is_self_referential": False,
        })

    def _guard_code(self, file_path):
        data = {"tool_name": "Edit", "tool_input": {"file_path": file_path}}
        with mock.patch.object(hooks_selfmod, "_resolveState", return_value=(self.state, True)), \
                mock.patch.object(hooks_selfmod, "_envTaskRequested", return_value=False):
            try:
                hooks.selfModificationGuard(data)
            except SystemExit as e:
                return int(e.code or 0)
        return 0

    def test_boundary_set_anchors_state_tasks(self):
        bset = hooks._boundarySetFor(self.state)
        anchored = str((config.PROJECT_ROOT / "state" / "tasks"))
        self.assertIn(anchored, bset)
        self.assertNotIn("state/tasks", bset)
        self.assertNotIn("state\\tasks", bset)
        self.assertIn(".env", bset, "secret/VCS baselines must stay relative (block in any repo)")
        self.assertIn(".git", bset)

    def test_install_task_store_is_blocked(self):
        path = str(config.PROJECT_ROOT / "state" / "tasks" / "abc.json")
        self.assertEqual(self._guard_code(path), 2, "9to5's own run state must still be protected")

    def test_external_repo_state_tasks_not_blocked(self):
        self.assertEqual(self._guard_code(r"C:\someproject\state\tasks\abc.json"), 0,
                         "a target repo's own state/tasks/ was falsely blocked")


class TestPrePrGateDeadline(unittest.TestCase):
    """#41: when the human pre_pr approval gate hits the deadline, the work is already done -- the run
    must finalize with its REAL status (flag set, no AbortRun), not be marked 'aborted'."""

    def _orch(self):
        orch = object.__new__(orchestrator.Orchestrator)
        orch._state_lock = threading.RLock()
        orch._pre_pr_gate_skipped = False
        orch._translateDiscord = lambda *a, **k: None
        orch._applyOps = lambda *a, **k: None
        orch._waitWhilePaused = lambda *a, **k: None
        orch._deadlinePassed = lambda s: True   # deadline already blown
        return orch

    def _bus(self):
        bus = mock.Mock()
        bus.isAbort.return_value = False
        bus.getDecision.return_value = None
        return bus

    def test_pre_pr_deadline_skips_pr_without_abort(self):
        orch = self._orch()
        state = types.SimpleNamespace(meta={"control_mode": "gated"}, task_id="t1")
        with mock.patch.object(orchestrator_control_mixin, "discord") as d, \
                mock.patch.object(orchestrator_control_mixin.time, "sleep"):
            d.gateNeededEmbed.return_value = {}
            d.humanPing.return_value = ""
            orch._checkControl(state, self._bus(), mock.Mock(), gate="pre_pr")  # must NOT raise
        self.assertTrue(orch._pre_pr_gate_skipped, "deadline at pre_pr gate must flag a PR-skip")

    def test_other_gate_deadline_still_aborts(self):
        orch = self._orch()
        state = types.SimpleNamespace(meta={"control_mode": "gated"}, task_id="t1")
        with mock.patch.object(orchestrator_control_mixin, "discord") as d, \
                mock.patch.object(orchestrator_control_mixin.time, "sleep"):
            d.gateNeededEmbed.return_value = {}
            d.humanPing.return_value = ""
            with self.assertRaises(orchestrator.AbortRun):
                orch._checkControl(state, self._bus(), mock.Mock(), gate="custom")


class TestAskAbortConfirm(unittest.IsolatedAsyncioTestCase):
    """#42: a NL imperative that maps to `abort` must require an explicit confirm; a cancelled or
    timed-out confirm leaves the run untouched (applyCommand never fires)."""

    async def _run(self, confirm_value):
        from notifications.bot.cogs import ask_cog

        class FakeView:
            def __init__(self, owner_id):
                self.value = confirm_value

            async def wait(self):
                return None

        cog = ask_cog.AskCog(bot=mock.Mock())
        interaction = mock.Mock()
        interaction.response.defer = mock.AsyncMock()
        interaction.followup.send = mock.AsyncMock()
        interaction.user.id = 123
        state = types.SimpleNamespace(task_id="t1", meta={})
        with mock.patch.object(ask_cog.config, "ASK_ENABLED", True), \
                mock.patch.object(ask_cog.config, "ASK_NL_CONTROL", True), \
                mock.patch.object(ask_cog.spine, "resolveTargetTask", return_value=state), \
                mock.patch.object(ask_cog.spine, "isAuthorized", return_value=True), \
                mock.patch.object(ask_cog.ask_mod, "detectControlIntent", return_value="abort"), \
                mock.patch.object(ask_cog.views, "ConfirmView", FakeView), \
                mock.patch.object(ask_cog.audit, "record") as rec, \
                mock.patch.object(ask_cog.spine, "applyCommand", return_value="aborted") as apply_cmd:
            # cog.ask is an app_commands.Command wrapper; invoke the raw coroutine with self.
            await ask_cog.AskCog.ask.callback(cog, interaction, "stop the run")
        return rec, apply_cmd

    async def test_abort_not_applied_without_confirm(self):
        rec, apply_cmd = await self._run(confirm_value=False)
        apply_cmd.assert_not_called()
        rec.assert_not_called()

    async def test_abort_applied_on_confirm(self):
        rec, apply_cmd = await self._run(confirm_value=True)
        apply_cmd.assert_called_once()
        rec.assert_called_once()


if __name__ == "__main__":
    unittest.main()
