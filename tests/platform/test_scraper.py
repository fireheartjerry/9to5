"""Tests for knowledge scraper text/provenance helpers."""
from __future__ import annotations

from platform_core.knowledge_base import scraper


def test_html_to_text_drops_script_and_keeps_visible_text():
    html = "<html><head>x</head><body><h1>Hello</h1><script>bad()</script><p>World</p></body></html>"

    text = scraper._htmlToText(html)

    assert "Hello" in text
    assert "World" in text
    assert "bad()" not in text


def test_fetch_docs_disabled_is_empty():
    result = scraper.fetchClaudeDocs(enabled=False)

    assert result["pages"] == {}
    assert result["ok"] == []
    assert result["failed"] == []
