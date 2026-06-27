"""Tests for the surface & tool catalog (rich cross-surface automation)."""
import unittest
from unittest import mock

import config
import platform_core.core.surfaces as surfaces


class TestCatalog(unittest.TestCase):
    def setUp(self):
        surfaces.reset_cache()

    def tearDown(self):
        mock.patch.stopall()
        surfaces.reset_cache()

    def test_available_includes_mcp_and_terminal(self):
        with mock.patch.object(config, "MCP_SERVERS", ("github", "gmail")):
            a = surfaces.available()
        self.assertTrue(a["terminal"])
        self.assertIn("github", a["mcp"])
        self.assertIn("gmail", a["mcp"])

    def test_catalog_block_lists_surfaces_and_directive(self):
        with mock.patch.object(config, "MCP_SERVERS", ("github", "google_calendar")):
            surfaces.reset_cache()
            block = surfaces.catalog_block()
        self.assertIn("AVAILABLE SURFACES", block)
        self.assertIn("do NOT default to the shell", block)
        self.assertIn("github", block)

    def test_browser_native_gated(self):
        with mock.patch.object(config, "BROWSER_LAYER_ENABLED", True), \
             mock.patch.object(config, "NATIVE_LAYER_ENABLED", False):
            a = surfaces.available()
        self.assertTrue(a["browser"])
        self.assertFalse(a["native"])


class TestSurfacesUsed(unittest.TestCase):
    def test_detects_mcp_skill_subagent(self):
        spec = {"prompt": "use mcp__github__create_pull_request and mcp__Gmail__send",
                "skills_to_invoke": ["/create-pr"], "subagent": "architect"}
        used = surfaces.surfaces_used(spec)
        self.assertIn("skill", used)
        self.assertIn("subagent", used)
        self.assertIn("mcp:github", used)
        self.assertIn("mcp:gmail", used)

    def test_detects_browser(self):
        self.assertIn("browser", surfaces.surfaces_used({"prompt": "navigate to https://x.com"}))

    def test_defaults_to_terminal(self):
        self.assertEqual(surfaces.surfaces_used({"prompt": "run pytest"}), ["terminal"])


if __name__ == "__main__":
    unittest.main()
