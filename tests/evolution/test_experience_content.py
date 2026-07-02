"""exp_content round-trip + importance scoring (tmp db, no embedder/Ollama needed)."""
import pytest

import config
from memory import experience, experience_content


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "experience.db"
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", p, raising=False)
    experience._reset_schema_cache()
    experience.init(db_path=p)
    yield p
    experience._reset_schema_cache()


def test_record_then_fetch_roundtrip(db):
    ok = experience_content.recordSolutionContent(
        "r1", "st-1", solution_content="diff: added retry to fetch()",
        post_mortem="timeout needed backoff", importance=2.5,
        model_id="claude-sonnet-4-6", db_path=db)
    assert ok is True
    row = experience_content.fetchSolutionContent("r1", "st-1", db_path=db)
    assert row["solution_content"] == "diff: added retry to fetch()"
    assert row["post_mortem"] == "timeout needed backoff"
    assert abs(row["importance"] - 2.5) < 1e-6


def test_fetch_missing_returns_none(db):
    assert experience_content.fetchSolutionContent("r1", "nope", db_path=db) is None


def test_record_upserts_on_conflict(db):
    experience_content.recordSolutionContent("r1", "st-1", solution_content="v1",
                                             post_mortem="", importance=1.0,
                                             model_id="m", db_path=db)
    experience_content.recordSolutionContent("r1", "st-1", solution_content="v2",
                                             post_mortem="", importance=1.0,
                                             model_id="m", db_path=db)
    assert experience_content.fetchSolutionContent("r1", "st-1", db_path=db)["solution_content"] == "v2"


def test_compute_importance_rewards_hard_won_contested_costly():
    base = experience_content.computeImportance(attempt_count=1, adversary_verdict="pass", cost_usd=0.0)
    harder = experience_content.computeImportance(attempt_count=3, adversary_verdict="challenged", cost_usd=2.0)
    assert harder > base
    assert experience_content.computeImportance(attempt_count=None) >= 1.0  # tolerant of nulls


def test_record_from_subtask_extracts_and_scores(db):
    st = {"subtask_id": "st-9", "title": "fix flaky test", "description": "make it deterministic",
          "_adversary_verdict": "challenged",
          "session": {"result_text": "rewrote sleep() as event wait", "model": "claude-opus-4-8",
                      "attempts": 2, "cost_usd": 1.5, "learning_summary": "avoid wall-clock sleeps"}}
    assert experience_content.recordFromSubtask("r2", st, db_path=db) is True
    row = experience_content.fetchSolutionContent("r2", "st-9", db_path=db)
    assert "event wait" in row["solution_content"]
    assert row["model_id"] == "claude-opus-4-8"
    assert row["importance"] > 1.0
