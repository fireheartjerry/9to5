"""Invention corpus: card loading, relevance retrieval, and prompt-block rendering.

Keyword-overlap retrieval is deterministic (no embeddings), so relevance assertions run
offline. A fake embedder exercises the semantic path.
"""
import re

import pytest

import config
from agents.discovery import corpus


@pytest.fixture(autouse=True)
def _fresh():
    corpus.reset_cache()
    yield
    corpus.reset_cache()


def fake_embed(text):
    toks = re.findall(r"[a-z]+", (text or "").lower())
    if not toks:
        return None
    import hashlib
    v = [0.0] * 64
    for t in toks:
        v[int(hashlib.md5(t.encode()).hexdigest(), 16) % 64] += 1.0
    return v


def test_all_cards_load_with_sections():
    cards = corpus.load_cards()
    assert len(cards) >= 10
    names = {c.name for c in cards}
    assert "map-elites-quality-diversity" in names
    assert "max-flow-portfolio-selection" in names
    for c in cards:
        assert "core mechanism" in c.sections    # required section parsed
        assert "transfer recipe" in c.sections


def test_relevant_query_retrieves_relevant_card():
    hits = corpus.retrieve("quality diversity archive coverage niches elites", k=3)
    assert hits
    assert hits[0].name == "map-elites-quality-diversity"


def test_portfolio_query_retrieves_portfolio_card():
    hits = corpus.retrieve("select candidate portfolio dependencies conflicts max flow cut", k=3)
    assert "max-flow-portfolio-selection" in {c.name for c in hits}


def test_irrelevant_query_does_not_crash_and_respects_k():
    hits = corpus.retrieve("banana pancake weather umbrella", k=2)
    assert len(hits) <= 2                         # never empty when cards exist, capped at k


def test_corpus_block_is_prompt_injectable():
    block = corpus.corpus_block("evidence grounded reporting facts assessments", k=2)
    assert "PRIOR ART" in block
    assert "evidence-grounded-reporting" in block
    assert "Transfer:" in block


def test_semantic_mode_with_injected_embedder():
    hits = corpus.retrieve("heterogeneous emitter bandit budget allocation", k=2, embed_fn=fake_embed)
    assert hits                                   # semantic path returns something, no crash


def test_disabled_flag_returns_empty(monkeypatch):
    monkeypatch.setattr(config, "INVENTION_CORPUS_ENABLED", False, raising=False)
    assert corpus.retrieve("anything", k=3) == []
    assert corpus.corpus_block("anything") == ""
