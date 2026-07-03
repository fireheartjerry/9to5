"""T8 Adversary duel VS-card: Pillow render + cast.duel gating (CHALLENGE-only, CAST_MODE-only)."""
import unittest

import config
from notifications import cast, visuals
from notifications import discord_bot as discord

PNG = b"\x89PNG\r\n\x1a\n"


class DuelRender(unittest.TestCase):
    def setUp(self):
        self._v = config.VISUALS_ENABLED
        config.VISUALS_ENABLED = True

    def tearDown(self):
        config.VISUALS_ENABLED = self._v

    def test_challenge_card_is_png(self):
        out = visuals.duelCard("st-004 build the parser", "challenged", trust=0.4)
        self.assertTrue(out.startswith(PNG))

    def test_approved_card_is_png(self):
        self.assertTrue(visuals.duelCard("st-001 scaffold", "approved").startswith(PNG))

    def test_none_when_disabled(self):
        config.VISUALS_ENABLED = False
        self.assertIsNone(visuals.duelCard("x", "challenged"))


class CastDuelGating(unittest.TestCase):
    def setUp(self):
        self._cast, self._vis = config.CAST_MODE, config.VISUALS_ENABLED
        config.VISUALS_ENABLED = True
        self.sent = []
        self._orig = discord.sendAs
        discord.sendAs = lambda persona, **kw: (self.sent.append((persona, kw)) or True)

    def tearDown(self):
        config.CAST_MODE, config.VISUALS_ENABLED = self._cast, self._vis
        discord.sendAs = self._orig

    def test_off_is_noop(self):
        config.CAST_MODE = False
        self.assertFalse(cast.duel("st-004", "challenged"))
        self.assertEqual(self.sent, [])

    def test_approved_does_not_duel(self):
        config.CAST_MODE = True
        self.assertFalse(cast.duel("st-004", "approved"))
        self.assertEqual(self.sent, [])

    def test_challenge_posts_card_as_adversary(self):
        config.CAST_MODE = True
        self.assertTrue(cast.duel("st-004 parser", "challenged", trust=0.5))
        self.assertEqual(len(self.sent), 1)
        persona, kw = self.sent[0]
        self.assertEqual(persona["icon"], "adversary")
        self.assertTrue(kw["files"][0][0] == "duel.png")
