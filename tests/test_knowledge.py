"""Unit tests for knowledge.py pure helpers + the capabilities injection that wraps
every Ollama system prompt."""
import unittest
from unittest import mock

import knowledge
import platform_core.knowledge_base.compress as knowledge_compress


class TestPureHelpers(unittest.TestCase):
    def test_parse_frontmatter(self):
        fm = knowledge._parseFrontmatter("---\nname: foo\ntags:\n  - a\n  - b\n---\nbody")
        self.assertEqual(fm["name"], "foo")
        self.assertEqual(fm["tags"], ["a", "b"])

    def test_parse_frontmatter_none(self):
        self.assertEqual(knowledge._parseFrontmatter("no frontmatter"), {})
        self.assertEqual(knowledge._parseFrontmatter("---\nunterminated: x"), {})

    def test_top_headings(self):
        self.assertEqual(knowledge._topHeadings("# T\n## A\ntext\n## B\n### C"), ["## A", "## B"])
        self.assertEqual(knowledge._topHeadings(""), [])

    def test_diff_headings(self):
        d = knowledge.diffHeadings("## A\n## B", "## B\n## C")
        self.assertEqual(d, {"added": ["## C"], "removed": ["## A"]})

    def test_html_to_text_strips_tags_and_scripts(self):
        out = knowledge._htmlToText("<h1>Title</h1><p>Hello <b>world</b></p><script>x=1</script>")
        self.assertIn("Title", out)
        self.assertIn("Hello world", out)
        self.assertNotIn("x=1", out)

    def test_executive_excerpt(self):
        text = "intro\n## Executive Recommendations\n- do x\n- do y\n## Other\nz"
        out = knowledge._executiveExcerpt(text)
        self.assertTrue(out.startswith("## Executive Recommendations"))
        self.assertIn("do y", out)
        self.assertNotIn("## Other", out)

    def test_executive_excerpt_empty(self):
        self.assertEqual(knowledge._executiveExcerpt(""), "")


class TestInjectCapabilities(unittest.TestCase):
    def setUp(self):
        self._saved = knowledge.getCapabilities()

    def tearDown(self):
        knowledge.setCapabilities(self._saved)

    def test_injects_cached_caps_before_prompt(self):
        knowledge.setCapabilities("CAPS-HERE")
        out = knowledge.injectCapabilities("SYSTEM-PROMPT")
        self.assertIn("CLAUDE CODE CAPABILITIES", out)
        self.assertIn("CAPS-HERE", out)
        self.assertTrue(out.endswith("SYSTEM-PROMPT"))

    def test_passthrough_when_no_caps(self):
        knowledge.setCapabilities("")
        with mock.patch.object(knowledge_compress, "ensureCapabilities", return_value=""):
            self.assertEqual(knowledge.injectCapabilities("SYS"), "SYS")


if __name__ == "__main__":
    unittest.main()
