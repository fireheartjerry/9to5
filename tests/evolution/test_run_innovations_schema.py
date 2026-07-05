"""Inventor Mega-Build persistence: run_innovations table + evolution_candidates novelty cols.

Mirrors tests/evolution/test_experience_schema.py conventions (tmp db, _reset_schema_cache).
The schema must be additive + idempotent so a legacy ledger upgrades in place.
"""
import sqlite3

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


def test_run_innovations_table_exists(db):
    cols = _cols(db, "run_innovations")
    assert {"id", "run_id", "title", "claim", "status", "measured_novelty", "qd_cell",
            "innovation_mechanism", "why_json", "how_json", "risk_json",
            "evidence_json", "created_at"} <= cols


def test_run_innovations_index_present(db):
    with experience._connect(db) as conn:
        idx = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_run_innovations_run" in idx


def test_evolution_candidates_novelty_columns(db):
    cols = _cols(db, "evolution_candidates")
    assert {"measured_novelty", "risk", "confidence", "subsystem",
            "design_sketch", "verify_plan"} <= cols


def test_run_innovations_unique_constraint(db):
    with experience._connect(db) as conn:
        conn.execute("INSERT INTO run_innovations (run_id, title, status) VALUES (?,?,?)",
                     ("r1", "Feature X", "shipped"))
    with experience._connect(db) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO run_innovations (run_id, title, status) VALUES (?,?,?)",
                         ("r1", "Feature X", "shipped"))


def test_schema_migration_is_idempotent_on_legacy_candidates(tmp_path):
    # Simulate an OLD ledger: evolution_candidates WITHOUT the novelty columns.
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE evolution_candidates (id INTEGER PRIMARY KEY, kind TEXT, "
                 "target TEXT, body TEXT, body_hash TEXT)")
    conn.execute("INSERT INTO evolution_candidates (kind, target, body, body_hash) "
                 "VALUES ('feature','memory','b','h')")
    conn.commit()
    conn.close()
    experience._reset_schema_cache()
    experience.init(db_path=db)     # must ALTER in place
    experience.init(db_path=db)     # second pass must not raise
    with experience._connect(db) as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(evolution_candidates)")}
        assert "measured_novelty" in cols
        row = conn.execute("SELECT target FROM evolution_candidates WHERE kind='feature'").fetchone()
        assert row["target"] == "memory"   # old reads still work
    experience._reset_schema_cache()
