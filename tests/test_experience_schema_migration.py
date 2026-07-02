"""Migration test: a pre-existing ledger gains exp_content + subtasks.importance idempotently."""
import sqlite3

import pytest

import config
from memory import experience


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    db = tmp_path / "experience.db"
    monkeypatch.setattr(config, "EXPERIENCE_DB_PATH", db, raising=False)
    experience._reset_schema_cache()
    yield db
    experience._reset_schema_cache()


def test_exp_content_table_and_importance_column_created(fresh_db):
    experience.init(db_path=fresh_db)
    with experience._connect(fresh_db) as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "exp_content" in tables
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(subtasks)")}
        assert "importance" in cols
        ccols = {r["name"] for r in conn.execute("PRAGMA table_info(exp_content)")}
        assert {"run_id", "st_id", "solution_content", "post_mortem",
                "importance", "model_id", "created_at"} <= ccols


def test_migration_is_idempotent_on_legacy_db(fresh_db):
    # Simulate an OLD ledger: subtasks table WITHOUT importance, no exp_content.
    conn = sqlite3.connect(fresh_db)
    conn.execute("CREATE TABLE subtasks (id INTEGER PRIMARY KEY, run_id TEXT, st_id TEXT)")
    conn.execute("INSERT INTO subtasks (run_id, st_id) VALUES ('r0','st-0')")
    conn.commit()
    conn.close()
    experience._reset_schema_cache()
    experience.init(db_path=fresh_db)           # ensure-schema must ALTER in place
    experience.init(db_path=fresh_db)           # second pass must not raise
    with experience._connect(fresh_db) as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(subtasks)")}
        assert "importance" in cols
        row = conn.execute("SELECT st_id FROM subtasks WHERE run_id='r0'").fetchone()
        assert row["st_id"] == "st-0"           # old reads still work
