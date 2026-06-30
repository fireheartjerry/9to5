"""retrieve_content must rerank by recency+importance+relevance after joining content."""
import pytest
from unittest import mock
from datetime import datetime, timedelta, timezone

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


def test_recent_important_row_floats_above_older_nearest_cosine(db, monkeypatch):
    now = datetime.now(timezone.utc)
    # OLD row: near-perfect cosine but stale + low importance.
    experience.record_subtask("r1", {"subtask_id": "old", "title": "old", "status": "done",
                                     "verify_result": {"passed": True}, "session": {"attempts": 1}}, db_path=db)
    experience.set_subtask_embedding("r1", "old", retrieval.pack([1.0, 0.0, 0.0]), db_path=db)
    experience_content.recordSolutionContent("r1", "old", solution_content="OLD answer",
                                             post_mortem="", importance=1.0, model_id="m", db_path=db)
    # NEW row: slightly worse cosine but recent + high importance.
    experience.record_subtask("r1", {"subtask_id": "new", "title": "new", "status": "done",
                                     "verify_result": {"passed": True}, "session": {"attempts": 1}}, db_path=db)
    experience.set_subtask_embedding("r1", "new", retrieval.pack([0.9, 0.1, 0.0]), db_path=db)
    experience_content.recordSolutionContent("r1", "new", solution_content="NEW answer",
                                             post_mortem="", importance=5.0, model_id="m", db_path=db)
    # Force created_at: old=120d ago, new=1d ago.
    with experience._connect(db) as conn:
        conn.execute("UPDATE exp_content SET created_at=? WHERE st_id='old'",
                     ((now - timedelta(days=120)).isoformat(),))
        conn.execute("UPDATE exp_content SET created_at=? WHERE st_id='new'",
                     ((now - timedelta(days=1)).isoformat(),))
    monkeypatch.setattr(exp_index, "getIndex", lambda: exp_index.NullIndex())  # use the scan path
    with mock.patch.object(retrieval, "_embed_call", return_value=[1.0, 0.0, 0.0]):
        hits = retrieval.retrieve_content("g", "t", db_path=db)
    assert hits[0]["solution_content"] == "NEW answer"
