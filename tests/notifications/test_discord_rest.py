"""Unit tests for the discord_bot REST chokepoint + embed clamping (no real network)."""
import contextlib
import unittest
from unittest import mock

import config
from notifications import discord_bot as d
from notifications import discord_client as _dc_mod


class _Resp:
    def __init__(self, status_code, body=None, text=""):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = text
        self.headers = {}

    def json(self):
        return self._body


@contextlib.contextmanager
def _cfg():
    # This module deliberately exercises the real _request() transport path (mocked Session,
    # not the network) -- opt out of the pytest-auto-detected _realDiscordBlocked guard so it
    # doesn't short-circuit before ever reaching the mocked Session.request.
    with mock.patch.multiple(config, DISCORD_BOT_TOKEN="t", DISCORD_CHANNEL_ID=123), \
            mock.patch.object(_dc_mod, "_realDiscordBlocked", return_value=False):
        yield


class TestRequest(unittest.TestCase):
    def setUp(self):
        d._DISABLED = False
        d._RATE_LIMITED_UNTIL = 0.0
        _dc_mod._CONSEC_401 = 0

    def tearDown(self):
        # These globals latch across calls; reset so state can't leak between tests (or to real use).
        d._DISABLED = False
        d._RATE_LIMITED_UNTIL = 0.0
        _dc_mod._CONSEC_401 = 0

    def test_429_then_success_retries(self):
        calls = []

        def fake(method, url, **kw):
            calls.append(1)
            return _Resp(429, {"retry_after": 0.0}) if len(calls) == 1 else _Resp(200, {"id": "9"})

        # NB: the code calls _SESSION.request (a requests.Session), NOT requests.request -- mocking the
        # module function would silently hit the real network. Patch the Session.
        with _cfg(), mock.patch.object(d._SESSION, "request", side_effect=fake), \
                mock.patch.object(d.time, "sleep"):
            r = d._request("POST", "/x")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(calls), 2)

    def test_401_latches_disabled(self):
        # two consecutive 401s latch the surface (a single transient 401 must not -- see
        # TestAuthLatchTwoStrike).
        with _cfg(), mock.patch.object(d._SESSION, "request", return_value=_Resp(401, text="bad")):
            d._request("GET", "/x")
            d._request("GET", "/x")
        self.assertTrue(d._DISABLED)
        with _cfg(), mock.patch.object(d._SESSION, "request") as m:
            self.assertIsNone(d._request("GET", "/x"))
            m.assert_not_called()

    def test_404_does_not_disable(self):
        with _cfg(), mock.patch.object(d._SESSION, "request", return_value=_Resp(404, text="gone")):
            d._request("DELETE", "/x")
        self.assertFalse(d._DISABLED)

    def test_control_poll_no_retry(self):
        with _cfg(), mock.patch.object(d._SESSION, "request", return_value=_Resp(429, {"retry_after": 99})) as m, \
                mock.patch.object(d.time, "sleep") as s:
            d._request("GET", "/x", retries=0)
        self.assertEqual(m.call_count, 1)
        s.assert_not_called()

    def test_429_arms_global_breaker_and_short_circuits(self):
        """A GLOBAL 429 must arm the global cooldown so the NEXT call short-circuits WITHOUT touching
        the network -- this is what stops the same-millisecond 429 storm in the logs. (A per-bucket
        429 deliberately does NOT arm it -- see TestRateLimitScope.)"""
        with _cfg(), mock.patch.object(d._SESSION, "request",
                                       return_value=_Resp(429, {"retry_after": 5, "global": True})) as m:
            # First poll hits the API once, sees 429, arms the breaker.
            d._request("GET", "/x", retries=0)
            self.assertEqual(m.call_count, 1)
            self.assertGreater(d._RATE_LIMITED_UNTIL, 0.0)
            # Subsequent calls (any path) short-circuit locally -- the Session is NOT hit again.
            self.assertIsNone(d._request("GET", "/x", retries=0))
            self.assertIsNone(d._request("POST", "/y"))
            self.assertEqual(m.call_count, 1)  # still 1 -- no further network calls during the window

    def test_breaker_window_expires(self):
        """Once the cooldown deadline passes, calls resume hitting the API."""
        with _cfg(), mock.patch.object(d._SESSION, "request", return_value=_Resp(200, {"id": "1"})) as m:
            d._RATE_LIMITED_UNTIL = d.time.monotonic() - 1.0   # already expired
            r = d._request("GET", "/x")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(m.call_count, 1)


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
        self.assertEqual(d.formatVerdict("approved"), "APPROVED")     # icon prefix '' unprovisioned
        self.assertEqual(d.formatVerdict("rejected"), "CHALLENGED")
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


class TestBlockedGuardLogging(unittest.TestCase):
    """The guard must LOG its refusal ONCE, never drop every Discord send silently -- silent
    refusal is what made a whole run's missing dashboard/terminal embeds undiagnosable."""

    def test_guard_logs_once_when_blocking(self):
        import contextlib
        import logging
        _dc_mod._DISABLED = False
        _dc_mod._RATE_LIMITED_UNTIL = 0.0
        records = []

        class _Cap(logging.Handler):
            def emit(self, r):
                records.append(r)

        cap = _Cap()
        _dc_mod.LOG.addHandler(cap)
        try:
            with contextlib.ExitStack() as es:
                es.enter_context(mock.patch.multiple(config, DISCORD_BOT_TOKEN="t", DISCORD_CHANNEL_ID=123))
                es.enter_context(mock.patch.object(_dc_mod, "_realDiscordBlocked", return_value=True))
                es.enter_context(mock.patch.object(_dc_mod, "_TEST_GUARD_LOGGED", False))
                self.assertIsNone(_dc_mod._request("POST", "/x", json={}, retries=0))
                self.assertIsNone(_dc_mod._request("POST", "/x", json={}, retries=0))
        finally:
            _dc_mod.LOG.removeHandler(cap)
        warnings = [r for r in records
                    if r.levelno == logging.WARNING and "test runner" in r.getMessage()]
        self.assertEqual(len(warnings), 1, "guard must log its refusal exactly once per process")


class TestGuardNoFalsePositiveInProd(unittest.TestCase):
    """Regression (2026-07-03): the ML/vector stack every real run loads pulls ``unittest`` into
    sys.modules (numpy.testing does ``from unittest import TestCase``; torch too). The OLD guard
    sniffed ``"unittest" in sys.modules`` and silently suppressed the live Discord dashboard +
    terminal on ordinary runs. A prod-like process (no pytest signals) with the ML stack loaded
    must NOT trip the guard."""

    def test_numpy_testing_import_does_not_block_discord_in_prod(self):
        import os
        import subprocess
        import sys
        from pathlib import Path

        root = Path(_dc_mod.__file__).resolve().parents[1]
        lines = [
            "import sys, numpy.testing",
            "assert 'unittest' in sys.modules",
            "from notifications import discord_client as dc",
            "assert dc._realDiscordBlocked() is False, 'guard false-positive: unittest present'",
            "print('PROD_OK')",
        ]
        code = chr(10).join(lines)
        env = {k: v for k, v in os.environ.items()
               if k not in ("PYTEST_CURRENT_TEST", "NINE_TO_FIVE_TEST_MODE")}
        r = subprocess.run([sys.executable, "-c", code], cwd=str(root),
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, f"stdout={r.stdout!r} stderr={r.stderr[-800:]!r}")
        self.assertIn("PROD_OK", r.stdout)


class TestContentClamp(unittest.TestCase):
    """Regression: sendEmbed/createMessage/createPoll/editMessageResult must clamp `content` to
    DISCORD_MAX_CONTENT (the embed was clamped but the sibling content field was not -> 400)."""

    def setUp(self):
        d._DISABLED = False
        d._RATE_LIMITED_UNTIL = 0.0

    def test_sendEmbed_clamps_long_content(self):
        captured = {}

        def fake(method, url, **kw):
            captured["content"] = (kw.get("json") or {}).get("content", "")
            return _Resp(200, {"id": "1"})

        with _cfg(), mock.patch.object(d._SESSION, "request", side_effect=fake):
            d.sendEmbed({}, content="x" * (config.DISCORD_MAX_CONTENT + 500))
        self.assertLessEqual(len(captured["content"]), config.DISCORD_MAX_CONTENT)


class TestAuthLatchTwoStrike(unittest.TestCase):
    """Regression: a single (possibly transient) 401 must NOT permanently disable Discord; only
    two consecutive 401s latch, and any 2xx resets the counter."""

    def setUp(self):
        d._DISABLED = False
        d._RATE_LIMITED_UNTIL = 0.0
        _dc_mod._CONSEC_401 = 0

    def tearDown(self):
        d._DISABLED = False
        _dc_mod._CONSEC_401 = 0

    def test_single_401_does_not_disable(self):
        with _cfg(), mock.patch.object(d._SESSION, "request", return_value=_Resp(401, text="bad")):
            d._request("GET", "/x")
        self.assertFalse(d._DISABLED)

    def test_two_consecutive_401s_disable(self):
        with _cfg(), mock.patch.object(d._SESSION, "request", return_value=_Resp(401, text="bad")):
            d._request("GET", "/x")
            d._request("GET", "/x")
        self.assertTrue(d._DISABLED)

    def test_success_between_401s_resets(self):
        with _cfg(), mock.patch.object(d._SESSION, "request", return_value=_Resp(401)):
            d._request("GET", "/x")
        with _cfg(), mock.patch.object(d._SESSION, "request", return_value=_Resp(200, {"id": "1"})):
            d._request("GET", "/x")
        with _cfg(), mock.patch.object(d._SESSION, "request", return_value=_Resp(401)):
            d._request("GET", "/x")
        self.assertFalse(d._DISABLED)


class TestRateLimitScope(unittest.TestCase):
    """Regression: a per-bucket 429 must not arm the process-wide breaker (which would stall the
    control poll + every other route); only a global 429 does."""

    def setUp(self):
        d._DISABLED = False
        d._RATE_LIMITED_UNTIL = 0.0

    def tearDown(self):
        d._RATE_LIMITED_UNTIL = 0.0

    def test_bucket_429_does_not_arm_global_breaker(self):
        with _cfg(), mock.patch.object(d._SESSION, "request",
                                       return_value=_Resp(429, {"retry_after": 0.0})),                 mock.patch.object(d.time, "sleep"):
            d._request("GET", "/x", retries=0)
        self.assertEqual(d._RATE_LIMITED_UNTIL, 0.0)

    def test_global_429_arms_breaker(self):
        with _cfg(), mock.patch.object(d._SESSION, "request",
                                       return_value=_Resp(429, {"retry_after": 2, "global": True})),                 mock.patch.object(d.time, "sleep"):
            d._request("GET", "/x", retries=0)
        self.assertGreater(d._RATE_LIMITED_UNTIL, 0.0)
