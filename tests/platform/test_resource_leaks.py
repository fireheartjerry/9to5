"""Resource-leak regressions from the gnarly audit:
- experience._new_conn must close the connection if schema/WAL setup raises (it was opened before
  being registered in _all_conns, so a failure leaked it).
- orchestrator._openGeminiSession must tear the session down if startConversation fails after a
  successful probe() (the session handle was assigned only AFTER startConversation, so a failure
  orphaned it)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from memory import experience
from memory import experience_schema


class TestNewConnNoLeakOnSchemaFailure(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"

    def test_conn_closed_and_not_registered_on_schema_error(self):
        before = len(experience._all_conns)
        experience._schema_ready.discard(str(self.db))
        with mock.patch.object(experience_schema, "_applyMigrations", side_effect=RuntimeError("bad migration")):
            with self.assertRaises(RuntimeError):
                experience_schema._new_conn(str(self.db), first=True)
        self.assertEqual(len(experience._all_conns), before, "connection leaked on schema failure")
        self.assertNotIn(str(self.db), experience._schema_ready)   # not marked -> next call retries clean

    def test_failed_lexical_close_remains_registered_and_propagates(self):
        class FailingConnection:
            def close(self):
                raise OSError("injected close failure")

        connection = FailingConnection()
        experience_schema._all_conns.append(connection)
        try:
            with self.assertRaises(OSError):
                experience_schema._evict(str(self.db), connection)
            self.assertIn(connection, experience_schema._all_conns)
        finally:
            if connection in experience_schema._all_conns:
                experience_schema._all_conns.remove(connection)


class TestGeminiSessionNoLeak(unittest.TestCase):
    def test_session_closed_when_startconversation_fails(self):
        from orchestrator import Orchestrator
        orch = Orchestrator(brain=mock.Mock(), obs=mock.Mock())
        state = mock.Mock()
        with mock.patch.object(config, "GEMINI_ENABLED", True), \
                mock.patch.object(orch, "_goalText", return_value="goal"), \
                mock.patch("agents.browser_executor.probe", return_value=True), \
                mock.patch("agents.browser_executor.startConversation", side_effect=RuntimeError("boom")), \
                mock.patch("agents.browser_executor.closeSession") as close, \
                mock.patch("platform_core.orchestration.review_mixin.discord"):
            orch._openGeminiSession(state)
        close.assert_called_once()              # the probe()-opened session was torn down
        self.assertIsNone(orch._gemini_session)
        self.assertFalse(orch._gemini_session_ok)
