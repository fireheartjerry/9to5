"""retrieve_content prefers the ANN index, falls back to scan; seeders populate the index."""
import pytest
from unittest import mock

import config
from memory import exp_index, experience, experience_content, retrieval


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "experience.db"
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", p, raising=False)
    monkeypatch.setattr(config, "EXPERIENCE_LEDGER_ENABLED", True, raising=False)
    experience._reset_schema_cache()
    retrieval.reset_embed_cache()
    exp_index.resetIndex()
    experience.init(db_path=p)
    yield p
    experience._reset_schema_cache()
    exp_index.resetIndex()


class _FakeIndex:
    def __init__(self): self.rows = []
    def addPair(self, uid, vec, payload): self.rows.append((uid, list(vec), dict(payload)))
    def query(self, vec, k, threshold):
        import math
        def cos(a, b):
            d = sum(x*y for x, y in zip(a, b))
            na = math.sqrt(sum(x*x for x in a))
            nb = math.sqrt(sum(y*y for y in b))
            return d/(na*nb) if na and nb else 0.0
        s = [{"uid": u, "score": cos(vec, v), "payload": p} for u, v, p in self.rows]
        s = [x for x in s if x["score"] >= threshold]
        s.sort(key=lambda x: x["score"], reverse=True)
        return s[:k]
    def persist(self): pass


def test_retrieve_content_uses_index_when_it_returns_hits(db, monkeypatch):
    fake = _FakeIndex()
    fake.addPair("r1::st-1", [1.0, 0.0, 0.0], {"run_id": "r1", "st_id": "st-1", "title": "x"})
    experience_content.recordSolutionContent("r1", "st-1", solution_content="indexed answer",
                                             post_mortem="", importance=1.0, model_id="m", db_path=db)
    monkeypatch.setattr(exp_index, "getIndex", lambda: fake)
    with mock.patch.object(retrieval, "_embed_call", return_value=[1.0, 0.0, 0.0]):
        hits = retrieval.retrieve_content("g", "t", db_path=db)
    assert hits and hits[0]["solution_content"] == "indexed answer"


def test_retrieve_content_falls_back_to_scan_on_empty_index(db, monkeypatch):
    experience.record_subtask("r1", {"subtask_id": "st-2", "title": "scan", "status": "done",
                                     "verify_result": {"passed": True}, "session": {"attempts": 1}}, db_path=db)
    experience.set_subtask_embedding("r1", "st-2", retrieval.pack([1.0, 0.0]), db_path=db)
    experience_content.recordSolutionContent("r1", "st-2", solution_content="scanned answer",
                                             post_mortem="", importance=1.0, model_id="m", db_path=db)
    monkeypatch.setattr(exp_index, "getIndex", lambda: exp_index.NullIndex())
    with mock.patch.object(retrieval, "_embed_call", return_value=[1.0, 0.0]):
        hits = retrieval.retrieve_content("g", "t", db_path=db)
    assert hits and hits[0]["solution_content"] == "scanned answer"


def test_embed_and_store_seeds_index(db, monkeypatch):
    fake = _FakeIndex()
    monkeypatch.setattr(exp_index, "getIndex", lambda: fake)
    experience.record_subtask("r1", {"subtask_id": "st-3", "title": "seed", "status": "done",
                                     "verify_result": {"passed": True}, "session": {"attempts": 1}}, db_path=db)
    with mock.patch.object(retrieval, "_embed_call", return_value=[0.3, 0.4, 0.5]):
        assert retrieval.embed_and_store("r1", "st-3", "goal", "seed", db_path=db) is True
    assert any(uid == "r1::st-3" for uid, _, _ in fake.rows)
