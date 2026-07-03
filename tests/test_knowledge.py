"""Unit tests for knowledge.py pure helpers + the capabilities injection that wraps
every Ollama system prompt."""
import unittest
from unittest import mock

import knowledge
import platform_core.knowledge_base.compress as knowledge_compress
import platform_core.knowledge_base.scraper as scraper


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


def _writeSkill(path, name):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: d\n---\nbody", encoding="utf-8")


def test_scan_excludes_nested_worktrees(tmp_path):
    """B33: scanLocalClaude must not descend into .claude/worktrees/** (nested repo copies)."""
    root = tmp_path / ".claude"
    _writeSkill(root / "skills" / "real" / "SKILL.md", "real-skill")
    _writeSkill(root / "worktrees" / "wt" / ".claude" / "skills" / "foreign" / "SKILL.md",
                "foreign-skill")
    inv = scraper.scanLocalClaude(roots=(root,))
    names = {s["name"] for s in inv["skills"]}
    assert "real-skill" in names
    assert "foreign-skill" not in names          # nested worktree surface not counted


def test_scan_excludes_vendored_subprojects(tmp_path):
    """B33: vendored sub-projects (fable-rewrite/**, nightclaw/**) are excluded too."""
    root = tmp_path / ".claude"
    _writeSkill(root / "skills" / "keep" / "SKILL.md", "keep")
    _writeSkill(root / "nightclaw" / ".claude" / "skills" / "drop" / "SKILL.md", "drop")
    inv = scraper.scanLocalClaude(roots=(root,))
    names = {s["name"] for s in inv["skills"]}
    assert "keep" in names and "drop" not in names


def test_read_product_self_knowledge_excludes_nested_worktrees(tmp_path):
    """Fresh bug hunt: readProductSelfKnowledge is a sibling of scanLocalClaude that never got
    the same .claude/worktrees exclusion -- a nested/foreign copy must not be picked up."""
    root = tmp_path / ".claude"
    foreign = root / "worktrees" / "wt" / ".claude" / "product-self-knowledge" / "SKILL.md"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_text("foreign product-self-knowledge", encoding="utf-8")
    out = scraper.readProductSelfKnowledge(roots=(root,))
    assert out["found"] is False


def test_read_product_self_knowledge_finds_real_skill(tmp_path):
    root = tmp_path / ".claude"
    real = root / "product-self-knowledge" / "SKILL.md"
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text("real product-self-knowledge", encoding="utf-8")
    out = scraper.readProductSelfKnowledge(roots=(root,))
    assert out["found"] is True
    assert "real product-self-knowledge" in out["text"]


if __name__ == "__main__":
    unittest.main()
