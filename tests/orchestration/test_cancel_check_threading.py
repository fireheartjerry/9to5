"""Every orchestrator-side Claude run must thread a cancel_check so the executor's session-token-limit
pause (which can block for HOURS) breaks early on abort/deadline. Previously architect, remediation,
and eval runs omitted it, so a pause during startup/eval wedged the whole run unbreakably."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from orchestrator import Orchestrator


class TestCancelCheckThreading(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._p = mock.patch.object(config, "STATE_DIR", self.dir)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_eval_run_threads_cancel_check(self):
        captured = {}

        def fake_run_claude(spec, **kw):
            captured["cancel_check"] = kw.get("cancel_check")
            return {"ok": True, "stdout": "ok", "stderr": "", "is_error": False}

        orch = Orchestrator(brain=mock.Mock(), obs=mock.Mock(), run_claude=fake_run_claude)
        with mock.patch.object(orch, "authorInvocationSpec", return_value={"prompt": "x"}), \
                mock.patch("orchestrator.verifier.runVerification", return_value={"passed": True}):
            orch._evalGoal({"goal": "do a thing", "verify": {}})

        self.assertTrue(callable(captured.get("cancel_check")),
                        "eval Claude run did not thread a cancel_check (pause would be unbreakable)")
        # the predicate must be callable and return a bool without raising
        self.assertIsInstance(captured["cancel_check"](), bool)
