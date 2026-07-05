"""Novelty index: measured novelty vs history, semantic dedup, and fail-open behavior.

Uses a deterministic bag-of-tokens fake embedder + an injected MemoryNoveltyStore so the
tests run with no Ollama and no chromadb. Paraphrases share tokens (high cosine -> low
novelty); unrelated text shares none (low cosine -> high novelty).
"""
import hashlib
import re

import pytest

from memory import novelty_index as ni
from memory.novelty_store import MemoryNoveltyStore

_DIM = 128


def fake_embed(text: str):
    """Stable bag-of-tokens vector: cosine reflects word overlap."""
    toks = re.findall(r"[a-z]+", (text or "").lower())
    if not toks:
        return None
    vec = [0.0] * _DIM
    for t in toks:
        vec[int(hashlib.md5(t.encode()).hexdigest(), 16) % _DIM] += 1.0
    return vec


A = "add persistent caching layer to accelerate memory retrieval lookups"
PARA = "accelerate memory retrieval with a persistent caching layer"
UNREL = "discord dashboard slash command notification embed styling colors"


@pytest.fixture()
def store():
    return MemoryNoveltyStore()


def _score(text, store, **kw):
    return ni.novelty_score(text, embed_fn=fake_embed, store=store, **kw)


def test_exact_duplicate_scores_low_novelty(store):
    ni.record_finding({"id": "a", "title": A}, embed_fn=fake_embed, store=store)
    r = _score(A, store)
    assert r.history_similarity_max > 0.99
    assert r.measured_novelty < 0.05
    assert r.nearest_id == "a"


def test_paraphrase_scores_low_novelty(store):
    ni.record_finding({"id": "a", "title": A}, embed_fn=fake_embed, store=store)
    r = _score(PARA, store)
    assert r.history_similarity_max > 0.6
    assert r.measured_novelty < 0.45


def test_unrelated_scores_high_novelty(store):
    ni.record_finding({"id": "a", "title": A}, embed_fn=fake_embed, store=store)
    r = _score(UNREL, store)
    assert r.history_similarity_max < 0.2
    assert r.measured_novelty > 0.8


def test_empty_history_is_maximally_novel(store):
    r = _score(A, store)
    assert r.measured_novelty == 1.0
    assert r.nearest_id == ""


def test_semantic_dedup_catches_paraphrases(store):
    items = [{"id": "a", "title": A}, {"id": "p", "title": PARA}, {"id": "u", "title": UNREL}]
    kept = ni.semantic_dedup(items, threshold=0.6, embed_fn=fake_embed,
                             key_fn=lambda x: x["title"])
    ids = {k["id"] for k in kept}
    assert "a" in ids and "u" in ids
    assert "p" not in ids               # paraphrase of A dropped
    assert len(kept) == 2


def test_semantic_dedup_keeps_distinct_items(store):
    items = [{"id": "a", "title": A}, {"id": "u", "title": UNREL}]
    kept = ni.semantic_dedup(items, threshold=0.6, embed_fn=fake_embed,
                             key_fn=lambda x: x["title"])
    assert len(kept) == 2


def test_compose_novelty_renormalizes_over_present_components():
    assert ni.compose_novelty(0.8) == 0.8                     # history alone -> identity
    blended = ni.compose_novelty(0.8, archive_cell_rarity=0.0)
    assert abs(blended - (0.45 * 0.8) / (0.45 + 0.20)) < 1e-6


def test_novelty_score_fails_open_on_embed_failure(store):
    r = ni.novelty_score(A, embed_fn=lambda t: None, store=store)
    assert r.degraded is True
    assert r.measured_novelty == 1.0        # permissive: never zeroes a candidate


def test_semantic_dedup_fails_open_when_embedding_unavailable():
    items = [{"title": A}, {"title": PARA}]
    kept = ni.semantic_dedup(items, threshold=0.6, embed_fn=lambda t: None,
                             key_fn=lambda x: x["title"])
    assert len(kept) == 2                    # cannot compare -> keep all


def test_nearest_history_returns_recorded_item(store):
    ni.record_finding({"id": "a", "title": A}, embed_fn=fake_embed, store=store)
    hits = ni.nearest_history(PARA, k=3, embed_fn=fake_embed, store=store)
    assert hits and hits[0]["uid"] == "a"


def test_appraisal_event_carries_measured_novelty(store):
    from human_nature import appraisal
    ni.record_finding({"id": "a", "title": A}, embed_fn=fake_embed, store=store)
    # A novel, successful event -> high novelty -> curiosity-eligible in appraisal.
    ev = ni.appraisal_event(UNREL, outcome="success", embed_fn=fake_embed, store=store)
    assert ev["novelty"] > 0.8
    pad = appraisal.appraise([ev])
    assert pad["vars"]["novelty"] > 0.8         # measured novelty flows into appraisal


def test_appraisal_event_degraded_novelty_is_zero(store):
    ev = ni.appraisal_event(A, embed_fn=lambda t: None, store=store)
    assert ev["novelty"] == 0.0                 # affect must not fake curiosity


def test_signature_text_handles_multiple_shapes():
    assert ni.signature_text("plain") == "plain"
    assert "memory" in ni.signature_text({"title": "T", "target_subsystems": ["memory"]})

    class _F:
        title = "T"
        rationale = "because"
        affected_files = ["x.py"]
    assert "because" in ni.signature_text(_F())
