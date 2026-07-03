"""Schema definition + migration tests for the Experience Ledger (memory/experience_schema.py).

Consolidated from test_evolution_schema.py, test_step_journal_schema.py,
test_experience_schema_migration.py, test_provenance_ledger.py, and
test_ledger_migration.py: all five verify tables/columns/indexes created (or
idempotently migrated) by memory/experience_schema.py, accessed either directly
or via the memory.experience facade.
"""
import os
import shutil
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

import config
from memory import experience
from memory import experience_schema as es


def _forceRmtree(path):
    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    shutil.rmtree(path, onerror=_onerror)


# ---------------------------------------------------------------------------
# evolution tables: insights + evolution_candidates + poignancy backfill
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# The step_journal table + index are created by the experience schema.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Migration test: a pre-existing ledger gains exp_content + subtasks.importance
# idempotently.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Ledger provenance columns (subtasks.adversary_stub/provenance,
# prompt_variants/reflections/solution_cache.provenance).
# ---------------------------------------------------------------------------

class TestLedgerProvenanceColumns(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_DB_PATH", self.db).start()
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()

    def tearDown(self):
        mock.patch.stopall()
        experience._reset_schema_cache()
        _forceRmtree(self.dir)

    def test_subtasks_has_adversary_stub_and_provenance(self):
        experience.init(self.db)
        with experience._connect(self.db) as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(subtasks)")}
        self.assertIn("adversary_stub", cols)
        self.assertIn("provenance", cols)

    def test_prompt_variants_and_reflections_and_cache_have_provenance(self):
        experience.init(self.db)
        with experience._connect(self.db) as conn:
            for table in ("prompt_variants", "reflections", "solution_cache"):
                cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                self.assertIn("provenance", cols, f"{table} missing provenance")


# ---------------------------------------------------------------------------
# The idempotent ADD COLUMN migration helper for the Experience Ledger.
# ---------------------------------------------------------------------------

class TestLedgerMigration(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_DB_PATH", self.db).start()
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()

    def tearDown(self):
        mock.patch.stopall()
        experience._reset_schema_cache()
        _forceRmtree(self.dir)

    def test_ensure_columns_adds_missing_column_idempotently(self):
        experience.init(self.db)
        with experience._connect(self.db) as conn:
            experience._ensureColumns(conn, "subtasks", {"spike_col": "INTEGER"})
            experience._ensureColumns(conn, "subtasks", {"spike_col": "INTEGER"})  # again
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(subtasks)")}
        self.assertIn("spike_col", cols)
