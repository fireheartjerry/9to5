"""The step_journal table + index are created by the experience schema."""
from memory import experience_schema as es


def test_step_journal_table_exists(tmp_path, monkeypatch):
    db = tmp_path / "experience.db"
    monkeypatch.setattr(es.config, "EXPERIENCE_DB_PATH", db)
    es._reset_schema_cache()
    es.init(db)
    with es._connect(db) as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        idx = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "step_journal" in tables
    assert "idx_journal_attempt" in idx
    es._reset_schema_cache()
