"""Real ChromaIndex round-trip (skipped unless chromadb is installed)."""
import pytest

import config
from memory import exp_index

chromadb = pytest.importorskip("chromadb")


@pytest.fixture(autouse=True)
def _reset():
    exp_index.resetIndex()
    yield
    exp_index.resetIndex()


def test_chromaindex_add_query_roundtrip_by_cosine(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANN_INDEX_DIR", str(tmp_path / "idx"), raising=False)
    monkeypatch.setattr(config, "ANN_EMBED_DIM", 3, raising=False)
    idx = exp_index.ChromaIndex(str(tmp_path / "idx"))
    idx.addPair("a", [1.0, 0.0, 0.0], {"st_id": "a", "run_id": "r1"})
    idx.addPair("b", [0.0, 1.0, 0.0], {"st_id": "b", "run_id": "r1"})
    idx.persist()
    hits = idx.query([1.0, 0.0, 0.0], 2, 0.0)
    assert hits[0]["uid"] == "a"
    assert hits[0]["payload"]["st_id"] == "a"
    assert hits[0]["score"] >= hits[1]["score"]


def test_getindex_returns_chroma_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANN_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "ANN_INDEX_DIR", str(tmp_path / "idx2"), raising=False)
    monkeypatch.setattr(config, "ANN_EMBED_DIM", 3, raising=False)
    assert isinstance(exp_index.getIndex(), exp_index.ChromaIndex)
