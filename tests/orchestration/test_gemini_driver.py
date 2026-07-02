"""GeminiSession + module-helper tests -- no real network. Focus mirrors the old chatgpt_driver
tests: the typed-error hierarchy, the under-test guard that refuses a real API call, the JSON /
response helpers, and the ask() contract (happy path, JSON-repair loop, safety block, turn
rollover). Every path that would otherwise reach the live API is mocked; the in-process guard
(``_realApiBlocked`` -> True under pytest) is an additional backstop, never the thing under test
for the ask/_send paths."""
import unittest
from unittest import mock

import config
from agents import gemini_driver as gd


# --- fakes ----------------------------------------------------------------------------------
class _FakeResp:
    """A stand-in for google-genai's GenerateContentResponse."""

    def __init__(self, text=None, *, raises_text=False, finish_reason=None):
        self._text = text
        self._raises_text = raises_text
        self.candidates = [mock.Mock(finish_reason=finish_reason)] if finish_reason is not None else []

    @property
    def text(self):
        if self._raises_text:
            raise RuntimeError(".text accessor raised (blocked/empty candidate)")
        return self._text


class _FakeChat:
    """A fake ``_chat`` whose send_message returns scripted replies (str or _FakeResp)."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.sent = []

    def send_message(self, message):
        self.sent.append(message)
        reply = self._replies.pop(0)
        return _FakeResp(text=reply) if isinstance(reply, str) else reply


def _open_session(chat):
    """A session that believes it is open, backed by a fake chat (no client built)."""
    sess = gd.GeminiSession()
    sess.opened = True
    sess._chat = chat
    sess._client = mock.Mock()
    sess._types = mock.Mock()
    return sess


# --- typed-error hierarchy ------------------------------------------------------------------
class TestErrorHierarchy(unittest.TestCase):
    def test_all_subclass_gemini_error_and_runtime_error(self):
        for cls in (gd.GeminiAuthError, gd.GeminiBlocked, gd.GeminiRateLimited, gd.GeminiUnavailable):
            self.assertTrue(issubclass(cls, gd.GeminiError))
            self.assertTrue(issubclass(cls, RuntimeError))

    def test_raise_typed_maps_rate_limit(self):
        with self.assertRaises(gd.GeminiRateLimited):
            gd._raiseTyped(RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded"))

    def test_raise_typed_maps_auth(self):
        with self.assertRaises(gd.GeminiAuthError):
            gd._raiseTyped(RuntimeError("API key not valid (permission_denied)"))

    def test_raise_typed_maps_transient_to_unavailable(self):
        with self.assertRaises(gd.GeminiUnavailable):
            gd._raiseTyped(RuntimeError("connection reset"))

    def test_raise_typed_honors_status_code(self):
        exc = RuntimeError("boom")
        exc.code = 429
        with self.assertRaises(gd.GeminiRateLimited):
            gd._raiseTyped(exc)


# --- under-test guard -----------------------------------------------------------------------
class TestRealApiBlocked(unittest.TestCase):
    def test_blocked_under_pytest(self):
        # pytest is in sys.modules during the suite, so the guard must refuse a real call.
        self.assertTrue(gd._realApiBlocked())

    def test_opt_in_env_disables_guard(self):
        with mock.patch.dict("os.environ", {"NINE_TO_FIVE_ALLOW_REAL_API": "1"}):
            self.assertFalse(gd._realApiBlocked())

    def test_test_mode_off_disables_guard(self):
        with mock.patch.dict("os.environ", {"NINE_TO_FIVE_TEST_MODE": "0"}):
            self.assertFalse(gd._realApiBlocked())

    def test_test_mode_on_forces_block(self):
        with mock.patch.dict("os.environ", {"NINE_TO_FIVE_TEST_MODE": "1"}):
            self.assertTrue(gd._realApiBlocked())


class TestBuildClient(unittest.TestCase):
    def test_blocked_under_test_raises_unavailable(self):
        sess = gd.GeminiSession()
        with self.assertRaises(gd.GeminiUnavailable):
            sess._build_client()           # guard is live under pytest

    def test_missing_key_raises_auth_when_guard_disabled(self):
        # Disable the guard + blank the key WITHOUT importing google-genai: the key check fires
        # before any SDK import, so this exercises the GeminiAuthError branch offline.
        sess = gd.GeminiSession()
        with mock.patch.object(gd, "_realApiBlocked", return_value=False), \
                mock.patch.object(config, "GEMINI_API_KEY", ""):
            with self.assertRaises(gd.GeminiAuthError):
                sess._build_client()


# --- pure helpers ---------------------------------------------------------------------------
class TestLooksLikeJson(unittest.TestCase):
    def test_object(self):
        self.assertTrue(gd._looks_like_json('{"a": 1}'))

    def test_fenced_object(self):
        self.assertTrue(gd._looks_like_json('```json\n{"a": 1}\n```'))

    def test_prose_is_not_json(self):
        self.assertFalse(gd._looks_like_json("hello there"))

    def test_none_is_not_json(self):
        self.assertFalse(gd._looks_like_json(None))


class TestResponseText(unittest.TestCase):
    def test_reads_text(self):
        self.assertEqual(gd._response_text(_FakeResp("  hi  ")), "hi")

    def test_falls_back_to_candidate_parts(self):
        part = mock.Mock(text="from parts")
        content = mock.Mock(parts=[part])
        cand = mock.Mock(content=content)
        resp = mock.Mock(spec=["candidates"])
        resp.text = None
        resp.candidates = [cand]
        self.assertEqual(gd._response_text(resp), "from parts")

    def test_empty_when_text_accessor_raises_and_no_parts(self):
        self.assertEqual(gd._response_text(_FakeResp(raises_text=True)), "")


class TestFinishReason(unittest.TestCase):
    def test_reads_first_candidate(self):
        self.assertEqual(gd._finish_reason(_FakeResp("x", finish_reason="SAFETY")), "SAFETY")

    def test_empty_when_no_candidates(self):
        self.assertEqual(gd._finish_reason(_FakeResp("x")), "")


# --- ask() contract -------------------------------------------------------------------------
class TestAskContract(unittest.TestCase):
    def test_happy_path_returns_reply(self):
        sess = _open_session(_FakeChat(['{"verdict": "approved"}']))
        with mock.patch.object(config, "GEMINI_MAX_TURNS", 100):
            self.assertEqual(sess.ask("review this", expect_json=True), '{"verdict": "approved"}')

    def test_json_repair_loop_recovers(self):
        # First reply is prose; one repair nudge then yields JSON.
        chat = _FakeChat(["here is prose", '{"verdict": "challenged"}'])
        sess = _open_session(chat)
        with mock.patch.object(config, "GEMINI_MAX_TURNS", 100), \
                mock.patch.object(config, "GEMINI_JSON_REPAIR_RETRIES", 1):
            self.assertEqual(sess.ask("give json", expect_json=True), '{"verdict": "challenged"}')
        self.assertEqual(len(chat.sent), 2)            # original + 1 repair nudge

    def test_persistent_prose_returns_none(self):
        # Never JSON, even after every repair: must be None (no usable reply), NOT the prose.
        chat = _FakeChat(["prose one", "prose two"])
        sess = _open_session(chat)
        with mock.patch.object(config, "GEMINI_MAX_TURNS", 100), \
                mock.patch.object(config, "GEMINI_JSON_REPAIR_RETRIES", 1):
            self.assertIsNone(sess.ask("give json", expect_json=True))

    def test_non_json_mode_returns_prose(self):
        sess = _open_session(_FakeChat(["just prose"]))
        with mock.patch.object(config, "GEMINI_MAX_TURNS", 100):
            self.assertEqual(sess.ask("chat", expect_json=False), "just prose")

    def test_safety_block_raises_blocked(self):
        # Empty reply + a safety finish_reason -> GeminiBlocked from _send.
        chat = _FakeChat([_FakeResp(text="", finish_reason="SAFETY")])
        sess = _open_session(chat)
        with mock.patch.object(config, "GEMINI_MAX_TURNS", 100):
            with self.assertRaises(gd.GeminiBlocked):
                sess.ask("trip the filter")

    def test_send_reraises_typed_on_sdk_error(self):
        bad = mock.Mock()
        bad.send_message.side_effect = RuntimeError("429 quota exhausted")
        sess = _open_session(bad)
        with self.assertRaises(gd.GeminiRateLimited):
            sess._send("hi")

    def test_turn_rollover_at_max_turns(self):
        sess = _open_session(_FakeChat(['{"ok": 1}']))
        sess._turns = 5
        captured = {}

        def fake_start(goal, task_id):
            captured["task_id"] = task_id
            sess._chat = _FakeChat(['{"ok": 1}'])
            sess._turns = 0

        with mock.patch.object(config, "GEMINI_MAX_TURNS", 5), \
                mock.patch.object(sess, "start_run_conversation", side_effect=fake_start):
            sess.ask("review", expect_json=True)
        self.assertEqual(captured.get("task_id"), "rollover")


# --- health_probe -----------------------------------------------------------------------
class TestHealthProbe(unittest.TestCase):
    def test_returns_false_and_never_raises_on_error(self):
        sess = gd.GeminiSession()
        # open() will build a client, which is blocked under pytest -> probe must swallow it.
        with mock.patch.object(sess, "open", side_effect=gd.GeminiUnavailable("blocked")):
            self.assertFalse(sess.health_probe())

    def test_returns_true_on_reply(self):
        sess = gd.GeminiSession()
        fake_client = mock.Mock()
        fake_client.models.generate_content.return_value = _FakeResp("pong")
        with mock.patch.object(sess, "open"):
            sess._client = fake_client
            sess._types = mock.Mock()
            self.assertTrue(sess.health_probe())

    def test_returns_false_on_empty_reply(self):
        sess = gd.GeminiSession()
        fake_client = mock.Mock()
        fake_client.models.generate_content.return_value = _FakeResp("")
        with mock.patch.object(sess, "open"):
            sess._client = fake_client
            sess._types = mock.Mock()
            self.assertFalse(sess.health_probe())
