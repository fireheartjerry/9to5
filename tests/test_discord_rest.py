"""Unit tests for the discord_bot REST chokepoint + embed clamping (no real network)."""
import unittest
from unittest import mock

import config
from notifications import discord_bot as d


class _Resp:
    def __init__(self, status_code, body=None, text=""):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = text
        self.headers = {}

    def json(self):
        return self._body


def _cfg():
    return mock.patch.multiple(config, DISCORD_BOT_TOKEN="t", DISCORD_CHANNEL_ID=123)


class TestRequest(unittest.TestCase):
    def setUp(self):
        d._DISABLED = False

    def tearDown(self):
        d._DISABLED = False   # the 401 test latches this global; reset so it can't leak to other modules

    def test_429_then_success_retries(self):
        calls = []

        def fake(method, url, **kw):
            calls.append(1)
            return _Resp(429, {"retry_after": 0.0}) if len(calls) == 1 else _Resp(200, {"id": "9"})

        with _cfg(), mock.patch.object(d.requests, "request", side_effect=fake), \
                mock.patch.object(d.time, "sleep"):
            r = d._request("POST", "/x")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(calls), 2)

    def test_401_latches_disabled(self):
        with _cfg(), mock.patch.object(d.requests, "request", return_value=_Resp(401, text="bad")):
            d._request("GET", "/x")
        self.assertTrue(d._DISABLED)
        with _cfg(), mock.patch.object(d.requests, "request") as m:
            self.assertIsNone(d._request("GET", "/x"))
            m.assert_not_called()

    def test_404_does_not_disable(self):
        with _cfg(), mock.patch.object(d.requests, "request", return_value=_Resp(404, text="gone")):
            d._request("DELETE", "/x")
        self.assertFalse(d._DISABLED)

    def test_control_poll_no_retry(self):
        with _cfg(), mock.patch.object(d.requests, "request", return_value=_Resp(429, {"retry_after": 99})) as m, \
                mock.patch.object(d.time, "sleep") as s:
            d._request("GET", "/x", retries=0)
        self.assertEqual(m.call_count, 1)
        s.assert_not_called()


class TestClampAndTruncate(unittest.TestCase):
    def test_truncate_marks_clip(self):
        self.assertEqual(d.truncate("abcdef", 4), "abc…")
        self.assertEqual(d.truncate("ab", 4), "ab")

    def test_clamp_field_value(self):
        e = {"fields": [{"name": "n", "value": "x" * 5000}]}
        out = d._clampEmbed(e)
        self.assertLessEqual(len(out["fields"][0]["value"]), config.DISCORD_MAX_FIELD_VALUE)

    def test_clamp_drops_beyond_25_fields(self):
        e = {"fields": [{"name": str(i), "value": "v"} for i in range(40)]}
        out = d._clampEmbed(e)
        self.assertEqual(len(out["fields"]), 25)

    def test_clamp_total_budget_shrinks(self):
        e = {"title": "t", "fields": [{"name": "n", "value": "y" * 2000} for _ in range(10)]}
        out = d._clampEmbed(e)
        self.assertLessEqual(d._embedLen(out), config.DISCORD_EMBED_TOTAL_MAX)
        self.assertEqual(len(out["fields"]), 10)  # rows preserved, values shrunk


class TestUnpinAndVerdict(unittest.TestCase):
    def test_unpin_404_is_success(self):
        with _cfg(), mock.patch.object(d, "_request", return_value=_Resp(404)):
            self.assertTrue(d.unpinMessage("5"))

    def test_unpin_none_message(self):
        self.assertFalse(d.unpinMessage(None))

    def test_formatVerdict_unknown(self):
        self.assertEqual(d.formatVerdict("approved"), "✅ APPROVED")
        self.assertEqual(d.formatVerdict("rejected"), "⚔️ CHALLENGED")
        self.assertIn("UNKNOWN", d.formatVerdict(""))
        self.assertIn("UNKNOWN", d.formatVerdict("pending"))


class TestFetch(unittest.TestCase):
    def test_author_id_surfaced(self):
        body = [{"id": "2", "content": "!abort", "author": {"id": "777", "bot": False}}]
        with _cfg(), mock.patch.object(d, "_request", return_value=_Resp(200, body)):
            msgs, latest = d.fetchMessagesAfter("1")
        self.assertEqual(msgs[0]["author_id"], "777")
        self.assertEqual(latest, "2")

    def test_baseline_returns_id_only(self):
        with _cfg(), mock.patch.object(d, "_request", return_value=_Resp(200, [{"id": "9"}])):
            self.assertEqual(d.baselineLatestId(), "9")


if __name__ == "__main__":
    unittest.main()
