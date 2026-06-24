"""Offline unit tests for the Phase-2 GPT-5.5 second-brain stack.

No browser / no Ollama: the Playwright-driven pieces are exercised through a fake page object,
and the brains are mocked. Covers chatgpt_selectors, chatgpt_driver pure logic, second_brain's
GPT->Ollama->stub chain + severity gating, the rich-verdict parse, and trust telemetry.
"""
import json
import unittest
from unittest import mock

import config
from agents import adversary, chatgpt_driver, chatgpt_selectors, second_brain


# --- fakes ----------------------------------------------------------------------------------
class FakeLoc:
    def __init__(self, n, text="", attr=None):
        self._n, self._text, self._attr = n, text, attr

    def count(self):
        return self._n

    @property
    def last(self):
        return FakeLoc(1, self._text, self._attr)

    def inner_text(self):
        return self._text

    def get_attribute(self, name):
        return self._attr

    def click(self):
        pass

    def press(self, *a, **k):
        pass

    def fill(self, *a, **k):
        pass

    def press_sequentially(self, *a, **k):
        pass

    def type(self, *a, **k):
        pass


class FakePage:
    """present: {css: (count, text)} -- everything else resolves to 0 elements."""

    def __init__(self, present):
        self.present = present
        self.url = "https://chatgpt.com/c/abc"

    def locator(self, css):
        n, text = self.present.get(css, (0, ""))
        return FakeLoc(n, text)

    def wait_for_timeout(self, ms):
        pass

    def goto(self, url):
        self.url = url

    def screenshot(self):
        return b""

    def content(self):
        return "<html></html>"


def _css(role):
    return chatgpt_selectors.DEFAULTS[role][0]


# --- chatgpt_selectors ----------------------------------------------------------------------
class TestSelectors(unittest.TestCase):
    def test_load_returns_default_lists(self):
        merged = chatgpt_selectors.load()
        self.assertIn("composer", merged)
        self.assertEqual(merged["composer"][0], chatgpt_selectors.DEFAULTS["composer"][0])

    def test_cached_selector_takes_precedence(self):
        with mock.patch.object(chatgpt_selectors, "_read_cache",
                               return_value={"selectors": {"composer": ".healed"}}):
            merged = chatgpt_selectors.load()
        self.assertEqual(merged["composer"][0], ".healed")
        self.assertIn(chatgpt_selectors.DEFAULTS["composer"][0], merged["composer"])

    def test_first_visible_picks_present(self):
        page = FakePage({_css("composer"): (1, "")})
        self.assertIsNotNone(chatgpt_selectors.first_visible(page, "composer"))
        self.assertIsNone(chatgpt_selectors.first_visible(page, "login_wall"))


# --- chatgpt_driver pure logic --------------------------------------------------------------
class TestDriverLogic(unittest.TestCase):
    def test_classify_ready(self):
        page = FakePage({_css("composer"): (1, "")})
        self.assertEqual(chatgpt_driver.classify_state(page), chatgpt_driver.READY)

    def test_classify_login_wall(self):
        page = FakePage({_css("login_wall"): (1, "")})
        self.assertEqual(chatgpt_driver.classify_state(page), chatgpt_driver.LOGIN_WALL)

    def test_classify_blockers_before_ready(self):
        # Cloudflare present alongside a composer must still classify as blocked.
        page = FakePage({_css("cloudflare"): (1, ""), _css("composer"): (1, "")})
        self.assertEqual(chatgpt_driver.classify_state(page), chatgpt_driver.CLOUDFLARE)

    def test_extract_latest_reply_uses_last(self):
        page = FakePage({_css("assistant_msg"): (3, "the newest turn")})
        self.assertEqual(chatgpt_driver.extract_latest_reply(page), "the newest turn")

    def test_extract_empty_when_no_assistant(self):
        self.assertEqual(chatgpt_driver.extract_latest_reply(FakePage({})), "")

    def test_await_reply_complete_returns_when_stable(self):
        page = FakePage({_css("assistant_msg"): (1, "done streaming")})  # no stop button => not streaming
        sess = chatgpt_driver.ChatGPTSession()
        sess._page = page
        sess.await_reply_complete(settle_ms=0, timeout_ms=2000)   # must return, not hang

    def test_looks_like_json(self):
        self.assertTrue(chatgpt_driver._looks_like_json('{"a":1}'))
        self.assertTrue(chatgpt_driver._looks_like_json('```json\n{"a":1}\n```'))
        self.assertFalse(chatgpt_driver._looks_like_json("hello"))


# --- rich verdict parsing -------------------------------------------------------------------
class TestRichVerdict(unittest.TestCase):
    def test_defaults_when_fields_missing(self):
        rv = adversary._parseVerdict({"verdict": "approved", "concerns": []}, "r", surface="browser")
        self.assertEqual(rv["severity"], "none")
        self.assertEqual(rv["must_fix"], [])
        self.assertIsNone(rv["confidence"])
        self.assertEqual(rv["review_type"], "subtask")

    def test_rich_fields_parsed(self):
        payload = {"verdict": "challenged", "severity": "high",
                   "must_fix": ["add a test", ""], "suggested_fix": "wrap in try",
                   "confidence": 0.8, "concerns": ["no test"]}
        rv = adversary._parseVerdict(payload, "r", surface="browser", review_type="pre_pr_diff")
        self.assertEqual(rv["severity"], "high")
        self.assertEqual(rv["must_fix"], ["add a test"])      # empty filtered
        self.assertEqual(rv["confidence"], 0.8)
        self.assertEqual(rv["review_type"], "pre_pr_diff")

    def test_challenged_defaults_to_medium_severity(self):
        rv = adversary._parseVerdict({"verdict": "rejected", "concerns": ["x"]}, "r", surface="browser")
        self.assertEqual(rv["verdict"], "challenged")
        self.assertEqual(rv["severity"], "medium")

    def test_systemFor_each_type_has_schema(self):
        for rt in second_brain.REVIEW_TYPES:
            self.assertIn("verdict", adversary.systemFor(rt))


# --- second_brain dispatch chain ------------------------------------------------------------
class TestConsultChain(unittest.TestCase):
    def setUp(self):
        self._p = mock.patch.object(config, "BROWSER_LAYER_ENABLED", True)
        self._p.start()

    def tearDown(self):
        mock.patch.stopall()

    def test_gpt_tier_when_browser_ok(self):
        ask = lambda m: json.dumps({"verdict": "approved", "concerns": []})
        rv = second_brain.consult("subtask", title="t", trigger_reason="r", content="out",
                                   browser_ask=ask, session_ok=True, worth=True)
        self.assertEqual(rv["tier"], "gpt")
        self.assertFalse(rv["stub"])
        self.assertFalse(rv["session_dead"])

    def test_falls_to_ollama_when_gpt_stubs(self):
        # browser_ask returns junk -> reviewViaBrowser stubs -> chain must try Ollama.
        chat = lambda system, user, *, want_json=False: {
            "message": {"content": json.dumps({"verdict": "approved", "concerns": []})}}
        rv = second_brain.consult("subtask", title="t", trigger_reason="r", content="out",
                                   browser_ask=lambda m: "not json", ollama_chat=chat,
                                   session_ok=True, worth=True)
        self.assertEqual(rv["tier"], "ollama")
        self.assertFalse(rv["stub"])

    def test_fatal_error_sets_session_dead(self):
        def boom(m):
            raise chatgpt_driver.ChatGPTLoginRequired("login wall")
        rv = second_brain.consult("subtask", title="t", trigger_reason="r", content="out",
                                   browser_ask=boom, ollama_chat=None, session_ok=True, worth=True)
        self.assertTrue(rv["session_dead"])
        self.assertTrue(rv["stub"])          # no ollama_chat -> stub tier
        self.assertEqual(rv["tier"], "stub")

    def test_skips_gpt_when_not_worth(self):
        called = {"n": 0}

        def ask(m):
            called["n"] += 1
            return json.dumps({"verdict": "approved", "concerns": []})
        rv = second_brain.consult("subtask", title="t", trigger_reason="r", content="x",
                                   browser_ask=ask, session_ok=True, worth=False)
        self.assertEqual(called["n"], 0)     # cost guard kept GPT out
        self.assertNotEqual(rv["tier"], "gpt")


class TestIsBlocking(unittest.TestCase):
    def test_approved_never_blocks(self):
        self.assertFalse(second_brain.is_blocking({"verdict": "approved", "tier": "gpt"}))

    def test_non_gpt_challenge_always_blocks(self):
        self.assertTrue(second_brain.is_blocking({"verdict": "challenged", "tier": "ollama"}))
        self.assertTrue(second_brain.is_blocking({"verdict": "challenged"}))  # missing tier => conservative

    def test_gpt_severity_gating(self):
        with mock.patch.object(config, "ADVERSARY_BLOCKING_SEVERITY", "high"):
            self.assertTrue(second_brain.is_blocking(
                {"verdict": "challenged", "tier": "gpt", "severity": "high"}))
            self.assertFalse(second_brain.is_blocking(
                {"verdict": "challenged", "tier": "gpt", "severity": "low"}))


# --- trust telemetry ------------------------------------------------------------------------
class TestTrustTelemetry(unittest.TestCase):
    def test_record_and_summary(self):
        import tempfile
        from pathlib import Path
        from learning import adversary_trust
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "trust.jsonl"
            with mock.patch.object(config, "ADVERSARY_TRUST_LOG", log):
                adversary_trust.record("subtask", {"verdict": "approved", "severity": "none"}, tier="gpt")
                adversary_trust.record("subtask", {"verdict": "challenged", "severity": "high"},
                                       tier="gpt", upheld=True)
                s = adversary_trust.summary()
            self.assertEqual(s["consults"], 2)
            self.assertEqual(s["gpt"], 2)
            self.assertEqual(s["challenges"], 1)
            self.assertEqual(s["upheld_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
