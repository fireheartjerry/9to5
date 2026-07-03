"""AnnIndex contract: NullIndex fail-open + getIndex singleton honoring ANN_INDEX_ENABLED.

Consolidated from test_exp_index.py and test_exp_index_chroma.py: both test
memory/exp_index.py -- the first with a NullIndex/FakeIndex test double (no
chromadb dependency needed), the second with a real ChromaIndex round-trip
(skipped unless chromadb is installed).
"""
import pytest

import config
from memory import exp_index


@pytest.fixture(autouse=True)
def _reset():
    exp_index.resetIndex()
    yield
    exp_index.resetIndex()


def test_nullindex_query_is_empty_and_addpair_is_noop():
    idx = exp_index.NullIndex()
    idx.addPair("u1", [1.0, 0.0], {"st_id": "st-1"})
    idx.persist()
    assert idx.query([1.0, 0.0], 5, 0.0) == []


def test_getindex_returns_null_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "ANN_INDEX_ENABLED", False, raising=False)
    assert isinstance(exp_index.getIndex(), exp_index.NullIndex)


def test_getindex_is_cached_singleton(monkeypatch):
    monkeypatch.setattr(config, "ANN_INDEX_ENABLED", False, raising=False)
    assert exp_index.getIndex() is exp_index.getIndex()


def test_getindex_falls_open_to_null_when_backend_import_fails(monkeypatch):
    monkeypatch.setattr(config, "ANN_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(exp_index, "_buildBackend", lambda: (_ for _ in ()).throw(ImportError("no chromadb")))
    assert isinstance(exp_index.getIndex(), exp_index.NullIndex)


def test_fakeindex_satisfies_protocol_and_ranks_by_cosine():
    # An in-memory test double proves the Protocol is usable WITHOUT chromadb as a test dep.
    fake = _FakeIndex()
    fake.addPair("a", [1.0, 0.0, 0.0], {"st_id": "a"})
    fake.addPair("b", [0.0, 1.0, 0.0], {"st_id": "b"})
    hits = fake.query([1.0, 0.0, 0.0], 2, 0.0)
    assert [h["uid"] for h in hits] == ["a", "b"]
    assert isinstance(fake, exp_index.AnnIndex)   # runtime_checkable Protocol


class _FakeIndex:
    def __init__(self):
        self._rows = []

    def addPair(self, uid, vec, payload):
        self._rows.append((uid, list(vec), dict(payload)))

    def query(self, vec, k, threshold):
        import math
        def cos(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            return dot / (na * nb) if na and nb else 0.0
        scored = [{"uid": u, "score": cos(vec, v), "payload": p} for u, v, p in self._rows]
        scored = [s for s in scored if s["score"] >= threshold]
        scored.sort(key=lambda s: s["score"], reverse=True)
        return scored[:k]

    def persist(self):
        pass


# ---------------------------------------------------------------------------
# Real ChromaIndex round-trip (skipped unless chromadb is installed).
#
# NOTE: the skip must be per-test (not a module-level pytest.importorskip), or
# it would also skip the chromadb-independent NullIndex/FakeIndex tests above
# when chromadb isn't installed.
# ---------------------------------------------------------------------------

try:
    import chromadb  # noqa: F401
    _HAS_CHROMADB = True
except ImportError:
    _HAS_CHROMADB = False


@pytest.mark.skipif(not _HAS_CHROMADB, reason="chromadb not installed")
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


@pytest.mark.skipif(not _HAS_CHROMADB, reason="chromadb not installed")
def test_getindex_returns_chroma_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANN_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "ANN_INDEX_DIR", str(tmp_path / "idx2"), raising=False)
    monkeypatch.setattr(config, "ANN_EMBED_DIM", 3, raising=False)
    assert isinstance(exp_index.getIndex(), exp_index.ChromaIndex)
