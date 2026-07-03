import pytest
from memory import experience


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "exp.db"
    experience._reset_schema_cache()
    experience.init(p)
    yield p
    experience._reset_schema_cache()


def _cols(db, table):
    with experience._connect(db) as conn:
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_insights_table_exists(db):
    cols = _cols(db, "insights")
    assert {"id", "scope", "text", "poignancy", "support_count",
            "win_rate", "depth", "provenance_json", "created_at"} <= cols


def test_evolution_candidates_table_exists(db):
    cols = _cols(db, "evolution_candidates")
    assert {"id", "kind", "target", "body", "body_hash", "parent_champion_id",
            "state", "n", "first_pass", "provenance_json"} <= cols


def test_poignancy_column_backfilled_on_subtasks_and_reflections(db):
    assert "poignancy" in _cols(db, "subtasks")
    assert "poignancy" in _cols(db, "reflections")
