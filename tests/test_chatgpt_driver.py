"""ChatGPTSession lifecycle tests -- no real browser. Focus: a failed health_probe must not
leak the launched Chromium context + Playwright driver (the orphaned-chrome / profile-lock
cascade), and close() must tear both down exactly once."""
import unittest
from unittest import mock

from agents import chatgpt_driver as cd


class TestHealthProbeLeak(unittest.TestCase):
    def _session_with_fake_browser(self):
        """A session that believes it has an open browser, backed by mocks (no Playwright)."""
        sess = cd.ChatGPTSession()
        sess._pw = mock.Mock(name="playwright")
        sess._ctx = mock.Mock(name="context")
        sess._page = mock.Mock(name="page")
        sess.opened = True
        return sess

    def test_probe_failure_closes_browser(self):
        """A login wall (or any post-open failure) must trigger close() so chrome/driver don't leak."""
        sess = self._session_with_fake_browser()
        ctx, pw = sess._ctx, sess._page  # capture before close() nulls them
        with mock.patch.object(cd, "classify_state", return_value=cd.LOGIN_WALL), \
                mock.patch.object(cd.profile_hygiene, "markCleanExit"):
            ok = sess.health_probe()
        self.assertFalse(ok)
        # The launched context + driver were torn down, and the session is marked closed so a later
        # open() starts fresh instead of reusing a half-dead session.
        ctx.close.assert_called_once()
        self.assertFalse(sess.opened)
        self.assertIsNone(sess._ctx)
        self.assertIsNone(sess._page)

    def test_probe_success_keeps_browser_open(self):
        """A healthy probe must NOT close the session (it's reused for the run)."""
        sess = self._session_with_fake_browser()
        ctx = sess._ctx
        with mock.patch.object(cd, "classify_state", return_value=cd.READY):
            ok = sess.health_probe()
        self.assertTrue(ok)
        ctx.close.assert_not_called()
        self.assertTrue(sess.opened)


class TestAskJsonContract(unittest.TestCase):
    def _open_session(self):
        sess = cd.ChatGPTSession()
        sess._pw, sess._ctx, sess._page = mock.Mock(), mock.Mock(), mock.Mock()
        sess.opened = True
        sess._conversation_url = "https://chatgpt.com/c/x"   # skip the goto branch
        return sess

    def test_expect_json_returns_none_when_reply_never_json(self):
        """Persistent prose must become None (no usable reply), never be returned as a 'verdict'."""
        sess = self._open_session()
        with mock.patch.object(sess, "_guard_state"), \
                mock.patch.object(sess, "_send_and_read", return_value="Sorry! Here is some prose."), \
                mock.patch.object(cd.config, "CHATGPT_JSON_REPAIR_RETRIES", 1), \
                mock.patch.object(cd.config, "CHATGPT_MAX_TURNS", 100):
            self.assertIsNone(sess.ask("give me json", expect_json=True))

    def test_expect_json_returns_json_when_valid(self):
        sess = self._open_session()
        with mock.patch.object(sess, "_guard_state"), \
                mock.patch.object(sess, "_send_and_read", return_value='{"verdict": "approved"}'), \
                mock.patch.object(cd.config, "CHATGPT_JSON_REPAIR_RETRIES", 1), \
                mock.patch.object(cd.config, "CHATGPT_MAX_TURNS", 100):
            self.assertEqual(sess.ask("give me json", expect_json=True), '{"verdict": "approved"}')


if __name__ == "__main__":
    unittest.main()
