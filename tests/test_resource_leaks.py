"""Resource-leak regressions from the gnarly audit:
- experience._new_conn must close the connection if schema/WAL setup raises (it was opened before
  being registered in _all_conns, so a failure leaked it).
- orchestrator._openChatGptSession must close the browser probe() opened if startConversation fails
  (the session handle was assigned only AFTER startConversation, so a failure orphaned Chromium)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from memory import experience


class TestNewConnNoLeakOnSchemaFailure(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"

    def test_conn_closed_and_not_registered_on_schema_error(self):
        before = len(experience._all_conns)
        experience._schema_ready.discard(str(self.db))
        with mock.patch.object(experience, "_applyMigrations", side_effect=RuntimeError("bad migration")):
            with self.assertRaises(RuntimeError):
                experience._new_conn(str(self.db), first=True)
        self.assertEqual(len(experience._all_conns), before, "connection leaked on schema failure")
        self.assertNotIn(str(self.db), experience._schema_ready)   # not marked -> next call retries clean


class TestChatGptSessionNoLeak(unittest.TestCase):
    def test_session_closed_when_startconversation_fails(self):
        from orchestrator import Orchestrator
        orch = Orchestrator(brain=mock.Mock(), obs=mock.Mock())
        state = mock.Mock()
        with mock.patch.object(config, "BROWSER_LAYER_ENABLED", True), \
                mock.patch.object(orch, "_goalText", return_value="goal"), \
                mock.patch("agents.browser_executor.probe", return_value=True), \
                mock.patch("agents.browser_executor.startConversation", side_effect=RuntimeError("boom")), \
                mock.patch("agents.browser_executor.closeSession") as close, \
                mock.patch("orchestrator.discord"):
            orch._openChatGptSession(state)
        close.assert_called_once()              # the probe()-opened browser was torn down
        self.assertIsNone(orch._chatgpt_session)
        self.assertFalse(orch._chatgpt_session_ok)


if __name__ == "__main__":
    unittest.main()
