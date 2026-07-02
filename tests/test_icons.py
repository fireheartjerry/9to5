"""App-emoji icon system: render PNGs offline + ensureIcons provisioning logic (monkeypatched
REST, no network) + graceful empty fallback."""
import json
import unittest

import config
from notifications import iconset, icons
from notifications import discord_bot as discord

PNG = b"\x89PNG\r\n\x1a\n"


class Render(unittest.TestCase):
    def setUp(self):
        self._v = config.VISUALS_ENABLED
        config.VISUALS_ENABLED = True

    def tearDown(self):
        config.VISUALS_ENABLED = self._v

    def test_render_is_rgba_png(self):
        out = iconset.renderIcon("done")
        self.assertTrue(out.startswith(PNG))
        from PIL import Image
        import io
        self.assertEqual(Image.open(io.BytesIO(out)).mode, "RGBA")

    def test_unknown_concept_none(self):
        self.assertIsNone(iconset.renderIcon("definitely-not-an-icon"))

    def test_all_curated_concepts_render(self):
        for c in iconset.EMOJI_CONCEPTS:
            self.assertTrue(iconset.renderIcon(c, size=64).startswith(PNG), c)


class Provision(unittest.TestCase):
    def setUp(self):
        icons._MAP = None
        icons._APP_ID = None
        self._orig = discord._request
        self.posted = []

        def fake(method, path, **kw):
            class R:
                status_code = 200
                def __init__(self, body):
                    self._b = body
                def json(self):
                    return self._b
            if path == "/applications/@me":
                return R({"id": "999"})
            if path == "/applications/999/emojis" and method == "GET":
                return R({"items": [{"name": "nc_done", "id": "111"}]})  # one already exists
            if path == "/applications/999/emojis" and method == "POST":
                self.posted.append(kw["json"]["name"])
                return R({"id": "222", "name": kw["json"]["name"]})
            return R({})
        discord._request = fake
        self._v = config.VISUALS_ENABLED
        config.VISUALS_ENABLED = True

    def tearDown(self):
        discord._request = self._orig
        config.VISUALS_ENABLED = self._v
        icons._MAP = None
        icons._APP_ID = None

    def test_icon_empty_before_provision(self):
        self.assertEqual(icons.icon("done"), "")

    def test_ensure_builds_map_and_reuses_existing(self):
        m = icons.ensureIcons()
        self.assertEqual(m["done"], "<:nc_done:111>")        # reused existing, not re-uploaded
        self.assertEqual(m["fail"], "<:nc_fail:222>")        # uploaded
        self.assertNotIn("nc_done", self.posted)             # existing one not posted
        self.assertIn("nc_fail", self.posted)
        self.assertEqual(icons.icon("done"), "<:nc_done:111>")
        self.assertTrue(icons.prefix("done").endswith(" "))
        self.assertEqual(icons.prefix("nope"), "")

    def test_transient_failure_is_not_latched(self):
        """B18: a first call that fails (no app id) must NOT cache an empty map; the next call,
        now succeeding, provisions icons instead of short-circuiting on the empty cache."""
        orig = discord._request

        def failing(method, path, **kw):
            if path == "/applications/@me":
                class R:
                    status_code = 500
                    def json(self):
                        return {}
                return R()
            return orig(method, path, **kw)

        icons._MAP = None
        icons._APP_ID = None
        discord._request = failing
        first = icons.ensureIcons()
        self.assertEqual(first, {})                 # failed
        self.assertIsNone(icons._MAP)               # and was NOT latched
        discord._request = orig                     # transient failure clears
        second = icons.ensureIcons()
        self.assertTrue(second)                     # now populated
        self.assertEqual(second["done"], "<:nc_done:111>")


if __name__ == "__main__":
    unittest.main()
