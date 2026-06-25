"""Theme-engine (T8 keystone) tests: palette/ansi/glyph/accent selection + fallback."""
import unittest

import config
from notifications import theme


class ThemeSelection(unittest.TestCase):
    def setUp(self):
        self._t = config.COCKPIT_THEME

    def tearDown(self):
        config.COCKPIT_THEME = self._t

    def test_default_dark(self):
        config.COCKPIT_THEME = "dark"
        self.assertEqual(theme.name(), "dark")
        self.assertEqual(theme.pillowPalette()["bg"], (24, 26, 33))

    def test_switch_terminal(self):
        config.COCKPIT_THEME = "terminal"
        self.assertEqual(theme.name(), "terminal")
        self.assertEqual(theme.ansiFrame(), "32")          # green frame
        self.assertEqual(theme.glyphs(), ("#", "-"))

    def test_unknown_falls_back(self):
        config.COCKPIT_THEME = "bogus"
        self.assertEqual(theme.name(), "dark")

    def test_ansi_status(self):
        self.assertEqual(theme.ansiStatus("executing"), "32")
        self.assertEqual(theme.ansiStatus("blocked"), "31")
        self.assertEqual(theme.ansiStatus("whatever"), "37")

    def test_status_fill_and_accent(self):
        self.assertEqual(theme.statusFill("done"), (46, 204, 113))
        self.assertIsInstance(theme.accent("executing"), int)

    def test_phase_emoji(self):
        self.assertEqual(theme.phaseEmoji("executing"), "⚙️")
        self.assertEqual(theme.phaseEmoji("???"), "🛰")


if __name__ == "__main__":
    unittest.main()
