"""Tests for The Cast: persona registry, CAST_MODE gating, and sendAs webhook semantics
(username override, never-ping, noauth). discord_bot transport is monkeypatched -> no network."""
import unittest

import config
from notifications import cast, personas
from notifications import discord_bot as discord


class _Resp:
    def __init__(self, status=204):
        self.status_code = status


class PersonaRegistry(unittest.TestCase):
    def test_known_role(self):
        p = personas.persona("adversary")
        self.assertEqual(p["name"], "Nightclaw · Adversary")   # clean text, no emoji
        self.assertEqual(p["icon"], "adversary")
        self.assertIn("avatar_url", p)

    def test_unknown_falls_back_to_brain(self):
        self.assertEqual(personas.persona("nobody")["icon"], "brain")

    def test_case_insensitive(self):
        self.assertEqual(personas.persona("ARCHITECT")["icon"], "architect")


class CastGating(unittest.TestCase):
    def setUp(self):
        self._cast, self._night = config.CAST_MODE, config.NIGHT_MODE
        self.sent = []
        self._orig_sendAs = discord.sendAs
        discord.sendAs = lambda persona, **kw: (self.sent.append((persona, kw)) or True)

    def tearDown(self):
        config.CAST_MODE, config.NIGHT_MODE = self._cast, self._night
        discord.sendAs = self._orig_sendAs

    def test_off_is_noop(self):
        config.CAST_MODE = False
        self.assertFalse(cast.speak("executor", "hi"))
        self.assertEqual(self.sent, [])

    def test_on_routes_persona(self):
        config.CAST_MODE = True
        self.assertTrue(cast.speak("adversary", "I challenge st-004"))
        self.assertEqual(len(self.sent), 1)
        persona, kw = self.sent[0]
        self.assertEqual(persona["icon"], "adversary")
        self.assertEqual(kw["content"], "I challenge st-004")   # icon prefix '' unprovisioned

    def test_milestone_suppressed_in_night(self):
        config.CAST_MODE = True
        config.NIGHT_MODE = True
        self.assertFalse(cast.speak("planner", "plan ready", milestone=True))
        self.assertEqual(self.sent, [])

    def test_empty_message_noop(self):
        config.CAST_MODE = True
        self.assertFalse(cast.speak("brain"))
        self.assertEqual(self.sent, [])


class SendAsSemantics(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._orig_ensure = discord._ensureWebhook
        self._orig_request = discord._request
        discord._ensureWebhook = lambda: "/webhooks/123/tok"

        def fake_request(method, path, **kw):
            self.calls.append((method, path, kw))
            return _Resp(204)

        discord._request = fake_request

    def tearDown(self):
        discord._ensureWebhook = self._orig_ensure
        discord._request = self._orig_request

    def test_username_override_and_no_ping_and_noauth(self):
        ok = discord.sendAs({"name": "Nightclaw · Adversary", "avatar_url": ""},
                            content="hello <@everyone>")
        self.assertTrue(ok)
        method, path, kw = self.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/webhooks/123/tok")
        self.assertTrue(kw.get("noauth"))
        body = kw["json"]
        self.assertEqual(body["username"], "Nightclaw · Adversary")
        self.assertEqual(body["allowed_mentions"], {"parse": []})   # never pings

    def test_silent_when_no_webhook(self):
        discord._ensureWebhook = lambda: None
        self.assertFalse(discord.sendAs({"name": "x"}, content="hi"))


if __name__ == "__main__":
    unittest.main()
