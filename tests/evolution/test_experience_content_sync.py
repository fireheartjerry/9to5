"""sync_subtask must ALSO persist solution content + denormalize importance onto subtasks."""
import pytest

import config
from memory import experience, experience_content


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "experience.db"
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", p, raising=False)
    monkeypatch.setattr(config, "EXPERIENCE_LEDGER_ENABLED", True, raising=False)
    experience._reset_schema_cache()
    experience.init(db_path=p)
    yield p
    experience._reset_schema_cache()


def _state(st):
    return {"task_id": "r1", "plan": {"subtasks": [st]}, "adversary_reviews": []}


def test_sync_subtask_writes_exp_content(db):
    st = {"subtask_id": "st-1", "title": "add cache", "description": "memoize lookups",
          "status": "done", "verify_result": {"passed": True},
          "session": {"attempts": 1, "model": "m", "result_text": "added lru_cache to lookup()"}}
    assert experience.sync_subtask(_state(st), st, db_path=db) is True
    row = experience_content.fetchSolutionContent("r1", "st-1", db_path=db)
    assert row is not None and "lru_cache" in row["solution_content"]


def test_sync_subtask_denormalizes_importance_onto_subtasks(db):
    st = {"subtask_id": "st-2", "title": "hard one", "description": "tricky",
          "status": "done", "verify_result": {"passed": True},
          "session": {"attempts": 3, "model": "m", "result_text": "fixed after 3 tries"}}
    experience.sync_subtask(_state(st), st, db_path=db)
    with experience._connect(db) as conn:
        imp = conn.execute("SELECT importance FROM subtasks WHERE st_id='st-2'").fetchone()["importance"]
    assert imp is not None and imp > 1.0
