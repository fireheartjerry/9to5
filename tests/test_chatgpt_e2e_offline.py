"""Offline event-matrix E2E for the chatgpt.com / Chrome integration.

Drives the REAL driver code (agents.chatgpt_driver / browser_executor / chatgpt_selectors /
vlm_healer / second_brain / profile_hygiene) through stateful FAKES -- never a real browser,
never the real profile/account -- to exercise the dynamic event branches the simpler unit
tests skip: streaming-settle-timeout, send-vs-Enter, multiline typing, the full VLM self-heal
loop (+cap/disabled), typed-error guards, turn rollover, JSON-repair, conversation start,
profile hygiene, thread-affinity, and the second-brain fatal/soft routing.

ISOLATION: every Playwright touchpoint is a fake page; psutil is mocked for the zombie-reap
test; the selector cache + Preferences file use temp dirs. No chrome.exe is ever launched.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow direct `python tests/...`

import config
from agents import browser_executor as be
from agents import chatgpt_driver as cd
from agents import chatgpt_selectors as sel
from agents import profile_hygiene, second_brain


def _css(role: str) -> str:
    return sel.DEFAULTS[role][0]


# --------------------------------------------------------------------------- fakes
class FakeLoc:
    def __init__(self, n, text="", attr=None, on_click=None, on_type=None):
        self._n, self._text, self._attr = n, text, attr
        self._on_click, self._on_type = on_click, on_type

    def count(self):
        return self._n

    @property
    def last(self):
        return self

    def inner_text(self):
        return self._text

    def get_attribute(self, name):
        return self._attr

    def click(self):
        if self._on_click:
            self._on_click()

    def press(self, *a, **k):
        if self._on_type:
            self._on_type(("press",) + a)

    def fill(self, *a, **k):
        if self._on_type:
            self._on_type(("fill",) + a)

    def press_sequentially(self, *a, **k):
        if self._on_type:
            self._on_type(("press_sequentially",) + a)

    def type(self, *a, **k):
        if self._on_type:
            self._on_type(("type",) + a)


class ScriptedPage:
    """A page whose visible elements come from a SEQUENCE of frames. Each wait_for_timeout
    advances to the next frame (clamped), so await_reply_complete sees the DOM change over
    'time'. ``frames`` is a list of {css: (count, text)} dicts."""

    def __init__(self, frames, *, url="https://chatgpt.com/c/abc", events=None):
        self.frames = frames or [{}]
        self.i = 0
        self.url = url
        self.events = events if events is not None else []

    def _present(self):
        return self.frames[min(self.i, len(self.frames) - 1)]

    def locator(self, css):
        n, text = self._present().get(css, (0, ""))
        return FakeLoc(n, text,
                       on_click=lambda: self.events.append(("click", css)),
                       on_type=lambda ev: self.events.append(("type", css, ev)))

    def wait_for_timeout(self, ms):
        self.i += 1

    def wait_for_selector(self, css, **k):
        if self._present().get(css, (0, ""))[0] > 0:
            return True
        raise RuntimeError(f"selector not visible: {css}")

    def goto(self, url, **k):
        self.url = url

    def screenshot(self, **k):
        return b"\x89PNG"

    def content(self):
        return "<html></html>"


def _session_on(page) -> cd.ChatGPTSession:
    s = cd.ChatGPTSession()
    s._pw, s._ctx, s._page = mock.Mock(), mock.Mock(), page
    s.opened = True
    return s


# ============================================================ 1. classify_state
class TestClassifyState(unittest.TestCase):
    def test_ready(self):
        self.assertEqual(cd.classify_state(ScriptedPage([{_css("composer"): (1, "")}])), cd.READY)

    def test_login_wall(self):
        self.assertEqual(cd.classify_state(ScriptedPage([{_css("login_wall"): (1, "")}])), cd.LOGIN_WALL)

    def test_cloudflare(self):
        self.assertEqual(cd.classify_state(ScriptedPage([{_css("cloudflare"): (1, "")}])), cd.CLOUDFLARE)

    def test_rate_limited(self):
        self.assertEqual(cd.classify_state(ScriptedPage([{_css("rate_limit"): (1, "")}])), cd.RATE_LIMITED)

    def test_blocker_beats_composer(self):
        page = ScriptedPage([{_css("cloudflare"): (1, ""), _css("composer"): (1, "")}])
        self.assertEqual(cd.classify_state(page), cd.CLOUDFLARE)

    def test_unknown_when_nothing(self):
        self.assertEqual(cd.classify_state(ScriptedPage([{}])), cd.UNKNOWN)


# ============================================================ 2-3. await_reply_complete
class TestAwaitReply(unittest.TestCase):
    def test_returns_after_stream_stops_and_settles(self):
        frames = [
            {_css("stop_button"): (1, ""), _css("assistant_msg"): (1, "partial")},
            {_css("stop_button"): (1, ""), _css("assistant_msg"): (1, "partial reply gro")},
            {_css("assistant_msg"): (1, "partial reply grown full")},
            {_css("assistant_msg"): (1, "partial reply grown full")},
            {_css("assistant_msg"): (1, "partial reply grown full")},
        ]
        page = ScriptedPage(frames)
        sess = _session_on(page)
        sess.await_reply_complete(settle_ms=1, timeout_ms=5000)
        self.assertEqual(cd.extract_latest_reply(page), "partial reply grown full")

    def test_timeout_does_not_hang(self):
        stuck = ScriptedPage([{_css("stop_button"): (1, ""), _css("assistant_msg"): (1, "still going")}])
        sess = _session_on(stuck)
        t0 = time.monotonic()
        sess.await_reply_complete(settle_ms=10, timeout_ms=300)   # must give up, not hang
        elapsed_ms = (time.monotonic() - t0) * 1000
        self.assertGreaterEqual(elapsed_ms, 250)
        self.assertLess(elapsed_ms, 5000)


# ============================================================ 4-6. _send_and_read
class TestSendAndRead(unittest.TestCase):
    def test_send_button_click_path(self):
        page = ScriptedPage([{_css("composer"): (1, ""), _css("send_button"): (1, ""),
                              _css("assistant_msg"): (1, "ANSWER")}])
        out = _session_on(page)._send_and_read("hello")
        clicks = [e[1] for e in page.events if e[0] == "click"]
        self.assertEqual(out, "ANSWER")
        self.assertIn(_css("send_button"), clicks)

    def test_enter_fallback_when_no_send_button(self):
        page = ScriptedPage([{_css("composer"): (1, ""), _css("assistant_msg"): (1, "VIA_ENTER")}])
        out = _session_on(page)._send_and_read("hello")
        presses = [e for e in page.events if e[0] == "type" and e[2][0] == "press"]
        self.assertEqual(out, "VIA_ENTER")
        self.assertTrue(any(len(e[2]) > 1 and "Enter" in str(e[2][1]) for e in presses))

    def test_multiline_uses_shift_enter(self):
        page = ScriptedPage([{_css("composer"): (1, ""), _css("send_button"): (1, ""),
                              _css("assistant_msg"): (1, "ok")}])
        _session_on(page)._send_and_read("line one\nline two\nline three")
        shift_enters = [e for e in page.events
                        if e[0] == "type" and e[2][0] == "press" and "Shift+Enter" in str(e[2][1:])]
        self.assertEqual(len(shift_enters), 2)


# ============================================================ 7-9. VLM self-heal
_HEALED = ".healed-composer"


class _HealPage(ScriptedPage):
    def locator(self, css):
        return FakeLoc(1, "") if css == _HEALED else FakeLoc(0, "")  # defaults all miss


class TestSelfHeal(unittest.TestCase):
    def test_heal_resolves_and_caches(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "sel.json"
            with mock.patch.object(config, "CHATGPT_SELECTOR_CACHE", cache), \
                 mock.patch.object(config, "VLM_SELF_HEAL_ENABLED", True), \
                 mock.patch.object(config, "VLM_SELF_HEAL_MAX_PER_RUN", 2), \
                 mock.patch("agents.vlm_healer.heal",
                            return_value={"state": "ready",
                                          "selectors": {"composer": _HEALED}, "confidence": 0.9}):
                sess = _session_on(_HealPage([{}]))
                loc = sess._resolve("composer")
                self.assertIsNotNone(loc)
                self.assertEqual(loc.count(), 1)
                saved = json.loads(cache.read_text(encoding="utf-8"))
                self.assertEqual(saved.get("selectors", {}).get("composer"), _HEALED)

    def test_heal_cap_zero_raises_without_calling_heal(self):
        with mock.patch.object(config, "VLM_SELF_HEAL_ENABLED", True), \
             mock.patch.object(config, "VLM_SELF_HEAL_MAX_PER_RUN", 0), \
             mock.patch("agents.vlm_healer.heal",
                        return_value={"selectors": {"composer": _HEALED}}) as h:
            sess = _session_on(_HealPage([{}]))
            with self.assertRaises(cd.ChatGPTSelectorMiss):
                sess._resolve("composer")
            self.assertEqual(h.call_count, 0)

    def test_heal_disabled_raises_without_calling_heal(self):
        with mock.patch.object(config, "VLM_SELF_HEAL_ENABLED", False), \
             mock.patch("agents.vlm_healer.heal") as h:
            sess = _session_on(_HealPage([{}]))
            with self.assertRaises(cd.ChatGPTSelectorMiss):
                sess._resolve("composer")
            self.assertEqual(h.call_count, 0)


# ============================================================ 10. ask() typed-error guards
class TestAskGuards(unittest.TestCase):
    def _assert_routes(self, state, exc):
        sess = _session_on(ScriptedPage([{}]))
        sess._conversation_url = "https://chatgpt.com/c/x"
        with mock.patch.object(cd, "classify_state", return_value=state):
            with self.assertRaises(exc):
                sess.ask("hi")

    def test_login_wall_routes(self):
        self._assert_routes(cd.LOGIN_WALL, cd.ChatGPTLoginRequired)

    def test_cloudflare_routes(self):
        self._assert_routes(cd.CLOUDFLARE, cd.ChatGPTBlocked)

    def test_rate_limit_routes(self):
        self._assert_routes(cd.RATE_LIMITED, cd.ChatGPTRateLimited)


# ============================================================ 11. turn rollover
class TestRollover(unittest.TestCase):
    def test_rollover_at_max_turns(self):
        sess = _session_on(ScriptedPage([{}]))
        sess._conversation_url = "https://chatgpt.com/c/x"
        sess._turns = 5
        rolled = {"n": 0}

        def _fake_start(goal, task_id):
            rolled["n"] += 1
            sess._turns = 0

        with mock.patch.object(cd, "classify_state", return_value=cd.READY), \
             mock.patch.object(config, "CHATGPT_MAX_TURNS", 5), \
             mock.patch.object(sess, "start_run_conversation", side_effect=_fake_start), \
             mock.patch.object(sess, "_send_and_read", return_value="ok"):
            sess.ask("trigger rollover")
        self.assertEqual(rolled["n"], 1)


# ============================================================ 12-13. JSON repair
class TestJsonRepair(unittest.TestCase):
    def test_prose_then_repair_returns_json(self):
        sess = _session_on(ScriptedPage([{}]))
        sess._conversation_url = "https://chatgpt.com/c/x"
        replies = iter(["here is prose, sorry", '{"verdict": "approved"}'])
        with mock.patch.object(cd, "classify_state", return_value=cd.READY), \
             mock.patch.object(config, "CHATGPT_JSON_REPAIR_RETRIES", 2), \
             mock.patch.object(config, "CHATGPT_MAX_TURNS", 100), \
             mock.patch.object(sess, "_send_and_read", side_effect=lambda m: next(replies)):
            self.assertEqual(sess.ask("give json", expect_json=True), '{"verdict": "approved"}')

    def test_persistent_prose_returns_none(self):
        sess = _session_on(ScriptedPage([{}]))
        sess._conversation_url = "https://chatgpt.com/c/x"
        with mock.patch.object(cd, "classify_state", return_value=cd.READY), \
             mock.patch.object(config, "CHATGPT_JSON_REPAIR_RETRIES", 1), \
             mock.patch.object(config, "CHATGPT_MAX_TURNS", 100), \
             mock.patch.object(sess, "_send_and_read", return_value="still prose forever"):
            self.assertIsNone(sess.ask("give json", expect_json=True))


# ============================================================ 14-15. start_run_conversation
class TestStartConversation(unittest.TestCase):
    def test_captures_in_project_url_and_resets_turns(self):
        proj_page = ScriptedPage([{}, {_css("composer"): (1, "")}],
                                 url="https://chatgpt.com/g/g-p-abc123/project")
        sess = _session_on(proj_page)
        with mock.patch.object(cd, "classify_state", return_value=cd.READY), \
             mock.patch.object(sess, "_await_composer", side_effect=lambda: None):
            sess.start_run_conversation("build x", "task-1")
        self.assertIn("g-p-", sess._conversation_url or "")
        self.assertEqual(sess._turns, 0)

    def test_login_wall_during_start_raises(self):
        sess = _session_on(ScriptedPage([{}]))
        with mock.patch.object(cd, "classify_state", return_value=cd.LOGIN_WALL):
            with self.assertRaises(cd.ChatGPTLoginRequired):
                sess.start_run_conversation("g", "t")


# ============================================================ 16. ensure_project cached
class TestEnsureProject(unittest.TestCase):
    def test_cached_short_circuit(self):
        with mock.patch.object(sel, "cached_project_url",
                               return_value="https://chatgpt.com/g/g-p-cached"):
            url = _session_on(ScriptedPage([{}])).ensure_project()
        self.assertEqual(url, "https://chatgpt.com/g/g-p-cached")


# ============================================================ 17. health_probe leak guard
class TestHealthProbe(unittest.TestCase):
    def test_success_keeps_open(self):
        sess = _session_on(ScriptedPage([{}]))
        ctx = sess._ctx
        with mock.patch.object(cd, "classify_state", return_value=cd.READY):
            ok = sess.health_probe()
        self.assertTrue(ok)
        self.assertTrue(sess.opened)
        self.assertEqual(ctx.close.call_count, 0)

    def test_failure_tears_down(self):
        sess = _session_on(ScriptedPage([{}]))
        ctx = sess._ctx
        with mock.patch.object(cd, "classify_state", return_value=cd.LOGIN_WALL), \
             mock.patch.object(cd.profile_hygiene, "markCleanExit"):
            ok = sess.health_probe()
        self.assertFalse(ok)
        self.assertFalse(sess.opened)
        self.assertEqual(ctx.close.call_count, 1)


# ============================================================ 18-20. profile hygiene
class _FakeProc:
    def __init__(self, name, cmdline):
        self.info = {"name": name, "cmdline": cmdline}
        self.killed = False

    def kill(self):
        self.killed = True


class TestProfileHygiene(unittest.TestCase):
    def test_killzombies_reaps_only_this_profile(self):
        profile = str(Path("C:/9to5/state/chatgpt_profile"))  # native form -> matches code's needle
        bind = _FakeProc("chrome.exe", ["chrome.exe", f"--user-data-dir={profile}", "--x"])
        other = _FakeProc("chrome.exe", ["chrome.exe", "--user-data-dir=C:/other/profile"])
        notchrome = _FakeProc("python.exe", ["python.exe", profile])
        fake_psutil = mock.Mock()
        fake_psutil.process_iter = mock.Mock(return_value=[bind, other, notchrome])
        with mock.patch.dict(sys.modules, {"psutil": fake_psutil}):
            profile_hygiene.killZombies(Path(profile))
        self.assertTrue(bind.killed)
        self.assertFalse(other.killed)
        self.assertFalse(notchrome.killed)

    def test_markcleanexit_resets_crash_flag(self):
        with tempfile.TemporaryDirectory() as d:
            pref = Path(d) / "Default" / "Preferences"
            pref.parent.mkdir(parents=True)
            pref.write_text(json.dumps({"profile": {"exit_type": "Crashed", "exited_cleanly": False}}),
                            encoding="utf-8")
            profile_hygiene.markCleanExit(Path(d))
            prof = json.loads(pref.read_text(encoding="utf-8"))["profile"]
            self.assertEqual(prof["exit_type"], "Normal")
            self.assertTrue(prof["exited_cleanly"])

    def test_sanitize_no_kill_runs_clean(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(profile_hygiene.sanitize(Path(d), kill=False), 0)


# ============================================================ 21. thread affinity
class TestThreadAffinity(unittest.TestCase):
    def test_ops_run_on_one_dedicated_thread(self):
        seen = set()

        def _probe():
            seen.add(threading.current_thread().name)
            return True

        for _ in range(3):
            be._call(_probe)
        self.assertEqual(len(seen), 1)
        self.assertNotIn(threading.current_thread().name, seen)
        self.assertTrue(all(t.startswith("chatgpt-session") for t in seen))


# ============================================================ 22. second_brain routing
class TestSecondBrainRouting(unittest.TestCase):
    def setUp(self):
        self._p = mock.patch.object(config, "BROWSER_LAYER_ENABLED", True)
        self._p.start()

    def tearDown(self):
        mock.patch.stopall()

    def test_fatal_gpt_error_sets_session_dead(self):
        def boom(m):
            raise cd.ChatGPTLoginRequired("wall")
        rv = second_brain.consult("subtask", title="t", trigger_reason="r", content="c",
                                   browser_ask=boom, ollama_chat=None, session_ok=True, worth=True)
        self.assertTrue(rv["session_dead"])
        self.assertEqual(rv["tier"], "stub")

    def test_soft_gpt_failure_falls_to_ollama(self):
        chat = lambda system, user, *, want_json=False: {
            "message": {"content": json.dumps({"verdict": "approved", "concerns": []})}}
        rv = second_brain.consult("subtask", title="t", trigger_reason="r", content="c",
                                   browser_ask=lambda m: "not json at all", ollama_chat=chat,
                                   session_ok=True, worth=True)
        self.assertEqual(rv["tier"], "ollama")
        self.assertFalse(rv["stub"])
        self.assertFalse(rv["session_dead"])


# ============================================================ 23. real-browser guard
class TestRealBrowserGuard(unittest.TestCase):
    """The hard backstop: no real Chromium launch under a test runner, and the conftest
    autouse fixture disables the browser layer + redirects the profile to a temp dir."""

    def test_launch_blocked_under_pytest(self):
        # A fresh session's _launch must refuse before importing/starting Playwright.
        with self.assertRaises(cd.ChatGPTError) as cm:
            cd.ChatGPTSession()._launch()
        self.assertIn("blocked", str(cm.exception).lower())

    def test_open_degrades_to_unavailable(self):
        # health_probe on a fresh session: open() -> _launch() raises -> caught -> False (degrade).
        sess = cd.ChatGPTSession()
        with mock.patch.object(cd.profile_hygiene, "markCleanExit"):
            self.assertFalse(sess.health_probe())
        self.assertFalse(sess.opened)

    def test_predicate_blocks_by_default(self):
        self.assertTrue(cd._realBrowserBlocked())   # pytest is in sys.modules

    def test_opt_in_env_allows_real_launch(self):
        with mock.patch.dict("os.environ", {"NINE_TO_FIVE_ALLOW_REAL_BROWSER": "1"}):
            self.assertFalse(cd._realBrowserBlocked())

    def test_explicit_test_mode_blocks(self):
        with mock.patch.dict("os.environ", {"NINE_TO_FIVE_TEST_MODE": "1",
                                            "NINE_TO_FIVE_ALLOW_REAL_BROWSER": ""}):
            self.assertTrue(cd._realBrowserBlocked())

    def test_conftest_disables_layer_and_redirects_profile(self):
        self.assertFalse(config.BROWSER_LAYER_ENABLED)
        self.assertIn("chatgpt_profile_test", str(config.CHATGPT_USER_DATA_DIR))


if __name__ == "__main__":
    unittest.main()
